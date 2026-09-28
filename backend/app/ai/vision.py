"""腾讯云图像识别客户端（TC3-HMAC-SHA256 签名，httpx 同步）。

目标接口：tiia DetectFood（菜品/食物识别）。注意：2026-08 腾讯云计费列表
未单列菜品识别，开通时需确认接口在售；若已下线，切换点见
docs/ai-provider-spike.md（改用视觉理解大模型或阿里云 DetectFood）。
"""

import base64
import datetime
import hashlib
import hmac
import json
import time

import httpx

from .base import VisionClient

_SERVICE = "tiia"
_HOST = "tiia.tencentcloudapi.com"
_VERSION = "2019-05-29"
_ACTION = "DetectFood"
# 超时：连接 3s / 读 30s（与服务端预算一致）
_TIMEOUT = httpx.Timeout(30.0, connect=3.0)

# spike 粗估表（kcal/100g）：真实热量应由服务层匹配 food 表后计算
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


def tc3_signature(
    secret_id: str, secret_key: str, payload: bytes, timestamp: int, action: str
) -> dict:
    """腾讯云 TC3-HMAC-SHA256 签名，返回可直接用于 httpx 的请求头。"""
    date = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).strftime(
        "%Y-%m-%d"
    )

    canonical_headers = (
        f"content-type:application/json; charset=utf-8\nhost:{_HOST}\n"
        f"x-tc-action:{action.lower()}\n"
    )
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(payload).hexdigest()
    canonical_request = f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n{hashed_payload}"

    credential_scope = f"{date}/{_SERVICE}/tc3_request"
    hashed_canonical_request = hashlib.sha256(
        canonical_request.encode("utf-8")
    ).hexdigest()
    string_to_sign = (
        f"TC3-HMAC-SHA256\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}"
    )

    k_date = hmac.new(
        f"TC3{secret_key}".encode("utf-8"), date.encode("utf-8"), hashlib.sha256
    ).digest()
    k_service = hmac.new(k_date, _SERVICE.encode("utf-8"), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(
        k_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    authorization = (
        f"TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": _HOST,
        "X-TC-Action": action,
        "X-TC-Version": _VERSION,
        "X-TC-Timestamp": str(timestamp),
    }


class TencentVisionClient(VisionClient):
    """腾讯云图像识别（tiia）。

    api_key 约定格式："{SecretId}:{SecretKey}"【假设】（TC3 签名需要两个值，
    .env.example 仅有一个 AI_VISION_API_KEY 变量，故用冒号拼接）。
    """

    def __init__(self, api_key: str, base_url: str | None = None):
        secret_id, _, secret_key = api_key.partition(":")
        if not secret_id or not secret_key:
            raise ValueError("AI_VISION_API_KEY 需为 'SecretId:SecretKey' 格式")
        self.secret_id = secret_id
        self.secret_key = secret_key
        url = base_url or f"https://{_HOST}"
        self.host = url.rstrip("/").removeprefix("https://").removeprefix("http://")

    def recognize_food(self, image_bytes: bytes) -> list[dict]:
        payload = json.dumps(
            {"ImageBase64": base64.b64encode(image_bytes).decode()}
        ).encode("utf-8")
        headers = tc3_signature(
            self.secret_id, self.secret_key, payload, int(time.time()), _ACTION
        )
        resp = httpx.post(f"https://{self.host}", headers=headers, content=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        body = resp.json().get("Response", {})
        if "Error" in body:
            err = body["Error"]
            raise RuntimeError(f"腾讯云识别失败: {err.get('Code')} {err.get('Message')}")

        items: list[dict] = []
        for food in body.get("FoodInfos", [])[:5]:  # 只取前 5 条，避免卡片过长
            name = food["Name"]
            confidence = round(food["Confidence"] / 100, 2)  # 腾讯云置信度 0-100
            kcal_100g = _ROUGH_KCAL_PER_100G.get(name, 200)  # 【假设】未命中粗估表按 200
            items.append(
                {
                    "name": name,
                    "confidence": confidence,
                    "calorie_estimate": round(kcal_100g * _DEFAULT_PORTION_G / 100),
                }
            )
        return items
