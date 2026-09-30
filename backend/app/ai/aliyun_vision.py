"""阿里云图像识别（食物类目）客户端 —— POP RPC 风格 V1 签名（httpx 同步）。

选型依据：主文档 §6.1 AI 行「视觉识别：腾讯云/阿里云图像识别（食物类目）」。

⚠️ **未联调**：沙箱无阿里云密钥、无法真机验证。域名 / Action / Version 均为【假设】，
上线前必须以阿里云「视觉智能开放平台」实时文档校正；返回结构按通用形态宽松解析，
真实字段名以官方文档为准。无 Key 时由 `factory` 回落 mock，不阻塞记录流程。

契约与 `app/ai/base.py` 的 `VisionClient.recognize_food(bytes)->list[dict]` 一致，
返回 `[{name, confidence, calorie_estimate}]`。
"""

import base64
import hashlib
import hmac
import time
import uuid
from urllib.parse import quote

import httpx

from .base import VisionClient

# 【假设】域名/Action/Version 未联调核对；可用 AI_VISION_BASE_URL 覆盖域名
_DEFAULT_HOST = "https://viapi.aliyuncs.com"
_DEFAULT_ACTION = "DetectFood"
_DEFAULT_VERSION = "2020-04-01"
_DEFAULT_REGION = "cn-shanghai"
# 超时：连接 3s / 读 30s（与服务端预算一致）
_TIMEOUT = httpx.Timeout(30.0, connect=3.0)

# 粗估表（kcal/100g）：真实热量由服务层匹配 food 表后计算（与腾讯云适配器同口径）
_ROUGH_KCAL_PER_100G = {
    "清蒸鱼": 120,
    "米饭": 116,
    "红烧肉": 480,
    "西红柿炒鸡蛋": 88,
    "宫保鸡丁": 210,
    "麻婆豆腐": 140,
    "炒青菜": 40,
    "煎鸡蛋": 195,
}
_DEFAULT_PORTION_G = 150  # 【假设】接口不返回份量，统一按 150g 估算


def _percent_encode(value: str) -> str:
    """RFC 3986 编码：仅保留 ~，其余非 unreserved 字符转义（阿里云签名要求）。"""
    return quote(str(value), safe="~")


def rpc_signature(access_key_id: str, access_key_secret: str, params: dict) -> dict:
    """阿里云 POP RPC V1 签名（HMAC-SHA1），返回可直接作为表单 body 的参数字典。"""
    params = {k: str(v) for k, v in params.items()}
    params.update(
        {
            "Format": "JSON",
            "AccessKeyId": access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureVersion": "1.0",
            "SignatureNonce": uuid.uuid4().hex,
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    canonical_query = "&".join(
        f"{_percent_encode(k)}={_percent_encode(params[k])}" for k in sorted(params)
    )
    string_to_sign = f"POST&{_percent_encode('/')}&{_percent_encode(canonical_query)}"
    signature = base64.b64encode(
        hmac.new(
            f"{access_key_secret}&".encode(),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode()
    params["Signature"] = signature
    return params


def _parse_items(body: dict) -> list[dict]:
    """阿里云响应 → `[{name, confidence, calorie_estimate}]`（宽松解析，最多 5 条）。"""
    data = body.get("Data") if isinstance(body, dict) else None
    raw_items = None
    for container in (data, body):
        if isinstance(container, dict):
            raw_items = container.get("FoodInfos") or container.get("items") or container.get(
                "Elements"
            )
            if raw_items:
                break

    items: list[dict] = []
    for raw in (raw_items or [])[:5]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("Name") or raw.get("name") or "").strip()
        if not name:
            continue
        try:
            confidence = float(raw.get("Confidence", raw.get("confidence", 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence > 1:  # 【假设】部分接口置信度为 0-100
            confidence = confidence / 100
        confidence = min(max(confidence, 0.0), 1.0)
        kcal_100g = _ROUGH_KCAL_PER_100G.get(name, 200)  # 【假设】未命中粗估表按 200
        items.append(
            {
                "name": name,
                "confidence": round(confidence, 2),
                "calorie_estimate": round(kcal_100g * _DEFAULT_PORTION_G / 100),
            }
        )
    return items


class AliyunVisionClient(VisionClient):
    """阿里云图像识别（RPC 风格）。

    api_key 约定格式："{AccessKeyId}:{AccessKeySecret}"【假设】（V1 签名需两个值，
    .env.example 仅有一个 AI_VISION_API_KEY 变量，故用冒号拼接，与腾讯云适配器一致）。
    """

    def __init__(self, api_key: str, base_url: str | None = None):
        access_key_id, _, access_key_secret = api_key.partition(":")
        if not access_key_id or not access_key_secret:
            raise ValueError("AI_VISION_API_KEY 需为 'AccessKeyId:AccessKeySecret' 格式")
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.host = (base_url or _DEFAULT_HOST).rstrip("/")

    def recognize_food(self, image_bytes: bytes) -> list[dict]:
        params = rpc_signature(
            self.access_key_id,
            self.access_key_secret,
            {
                "Action": _DEFAULT_ACTION,
                "Version": _DEFAULT_VERSION,
                "RegionId": _DEFAULT_REGION,
                "ImageBase64": base64.b64encode(image_bytes).decode(),
            },
        )
        resp = httpx.post(f"{self.host}/", data=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, dict) and body.get("Code"):  # 阿里云错误形如 {"Code": "..."}
            raise RuntimeError(f"阿里云识别失败: {body.get('Code')} {body.get('Message')}")
        return _parse_items(body)
