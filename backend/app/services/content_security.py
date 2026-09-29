"""内容安全服务（BE7c）：文本/图片审核 + XSS 转义。

设计（与仓库 `app/ai/` "无 Key 落 mock" 同风格）：
- 有微信内容安全凭据（WECHAT_APPID/SECRET）时调用 msgSecCheck / imgSecCheck；
- 无凭据 / 调用异常时自动降级为本地违规词 / 违规图 mock，零网络依赖、永远可用。

返回 `SecurityResult(passed, result)`：result 1通过 2可疑 3不通过（对齐 review.sec_check_result）。
违规内容由调用方入库 `audit_status=0` 并写入 `review` 待审队列，不直接对外展示。
"""

from __future__ import annotations

import html
from typing import NamedTuple

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SEC_PASS = 1  # 通过
SEC_SUSPECT = 2  # 可疑
SEC_REJECT = 3  # 不通过

# 本地违规词（mock 降级用；命中即判不通过）
_DEFAULT_BAD_WORDS: tuple[str, ...] = (
    "违规词",
    "涉政",
    "赌博",
    "色情",
    "暴力",
    "诈骗",
    "违禁",
    "法轮",
    "fuck",
    "fxxk",
)

# 本地违规图标记（mock 降级用；URL 命中即判不通过）
_DEFAULT_BAD_IMAGE_MARKERS: tuple[str, ...] = (
    "violation",
    "illegal",
    "badimg",
    "porn",
    "weapon",
)


class SecurityResult(NamedTuple):
    """审核结果：`(passed, result, reason)`。"""

    passed: bool
    result: int
    reason: str | None = None


def _settings() -> Settings:
    return get_settings()


def escape_html(text: str) -> str:
    """XSS 转义：< > & " ' 转为 HTML 实体（含单引号，防属性注入）。"""
    return html.escape(text, quote=True)


def _local_text_check(text: str) -> SecurityResult:
    for word in _DEFAULT_BAD_WORDS:
        if word in text:
            return SecurityResult(False, SEC_REJECT, f"命中违规词：{word}")
    return SecurityResult(True, SEC_PASS)


def _local_image_check(image_url: str) -> SecurityResult:
    lowered = image_url.lower()
    for marker in _DEFAULT_BAD_IMAGE_MARKERS:
        if marker in lowered:
            return SecurityResult(False, SEC_REJECT, f"图片可疑：{marker}")
    return SecurityResult(True, SEC_PASS)


async def _wechat_available() -> bool:
    s = _settings()
    return bool(getattr(s, "WECHAT_APPID", "") and getattr(s, "WECHAT_SECRET", ""))


async def check_text(text: str) -> SecurityResult:
    """文本审核：有微信凭据走 msgSecCheck，否则本地违规词 mock。异常一律降级 mock。"""
    if await _wechat_available():
        try:
            return await _wechat_msg_sec_check(text)  # pragma: no cover - 无 Key 环境不触发
        except Exception as exc:  # noqa: BLE001 - 安全接口不可用须降级，不得阻断发布
            logger.warning(f"msgSecCheck 调用失败，降级本地违规词校验: {exc}")
    return _local_text_check(text)


async def check_image(image_url: str) -> SecurityResult:
    """图片审核：有微信凭据走 imgSecCheck，否则本地违规图 mock。异常一律降级 mock。"""
    if await _wechat_available():
        try:
            return await _wechat_img_sec_check(image_url)  # pragma: no cover - 无 Key 环境不触发
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"imgSecCheck 调用失败，降级本地违规图校验: {exc}")
    return _local_image_check(image_url)


async def scan(content: str, images: list[str] | None = None) -> SecurityResult:
    """综合审核：文本优先，任一图片违规即不通过。"""
    result = await check_text(content or "")
    if not result.passed:
        return result
    for url in images or []:
        img = await check_image(url)
        if not img.passed:
            return img
    return SecurityResult(True, SEC_PASS)


# ---- 微信内容安全接口占位（有凭据时启用；无 Key 环境不进入）----


async def _wechat_access_token() -> str:  # pragma: no cover - 依赖真实凭据
    import httpx

    s = _settings()
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(
            "https://api.weixin.qq.com/cgi-bin/token",
            params={
                "grant_type": "client_credential",
                "appid": s.WECHAT_APPID,
                "secret": s.WECHAT_SECRET,
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def _wechat_msg_sec_check(text: str) -> SecurityResult:  # pragma: no cover - 依赖真实凭据
    import httpx

    token = await _wechat_access_token()
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.post(
            "https://api.weixin.qq.com/wxa/msg_sec_check",
            params={"access_token": token},
            json={"version": 2, "scene": 2, "content": text},
        )
        resp.raise_for_status()
        data = resp.json()
    # suggest: risky / review / pass
    suggest = (data.get("result") or {}).get("suggest")
    if suggest == "risky":
        return SecurityResult(False, SEC_REJECT, "微信内容安全判定违规")
    if suggest == "review":
        return SecurityResult(True, SEC_SUSPECT, "微信内容安全建议人工复核")
    return SecurityResult(True, SEC_PASS)


async def _wechat_img_sec_check(image_url: str) -> SecurityResult:  # pragma: no cover
    import httpx

    token = await _wechat_access_token()
    async with httpx.AsyncClient(timeout=8) as client:
        img = await client.get(image_url)
        img.raise_for_status()
        resp = await client.post(
            "https://api.weixin.qq.com/wxa/img_sec_check",
            params={"access_token": token},
            files={"media": img.content},
        )
        resp.raise_for_status()
        data = resp.json()
    if data.get("errcode") == 87014:
        return SecurityResult(False, SEC_REJECT, "微信图片安全判定违规")
    return SecurityResult(True, SEC_PASS)
