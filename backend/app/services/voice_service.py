"""语音转写服务（G4）：ASR 装配 + 未配置时明确降级。

契约 `/api/ai/voice-transcribe`：入参 `{audio_base64, format}`、出参 `{text, provider}`。
本仓库当前**无 ASR 配置**（Settings 无 ASR_* 字段、亦无 ASR 依赖）：
按契约结构明确降级返回 `{text: "", provider: "disabled"}`，HTTP 200，绝不 500。

【假设】降级标识口径：契约 `VoiceTranscribeData.provider` 描述仅举例 "local-fallback"；
本波按任务要求统一使用 `"disabled"` 表示「未配置 ASR、功能未启用」。未来接入真实 ASR
（如 `ASR_BASE_URL`/`ASR_API_KEY` 齐备）时，在此函数内接真实调用并回填 `text`。
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.config import Settings, get_settings

# 未配置 ASR 时的降级 provider 标识
DISABLED_PROVIDER = "disabled"


class VoiceTranscribeIn(BaseModel):
    """语音转写入参（契约 VoiceTranscribeIn）。"""

    audio_base64: str
    format: str


class VoiceTranscribeData(BaseModel):
    """语音转写响应（契约 VoiceTranscribeData）。"""

    text: str
    provider: str


def asr_configured(settings: Settings) -> bool:
    """是否已配置 ASR：同时具备 base_url 与 api_key（当前仓库恒 False）。"""
    return bool(
        getattr(settings, "ASR_BASE_URL", "") and getattr(settings, "ASR_API_KEY", "")
    )


async def transcribe(
    audio_base64: str, audio_format: str, settings: Settings | None = None
) -> VoiceTranscribeData:
    """语音转文字：未配置 ASR → 明确降级（provider="disabled"、text=""）。"""
    s = settings or get_settings()
    if not asr_configured(s):
        return VoiceTranscribeData(text="", provider=DISABLED_PROVIDER)
    # 预留真实 ASR 调用分支（当前仓库无 ASR 依赖，配置齐备前不可达）
    return VoiceTranscribeData(text="", provider=DISABLED_PROVIDER)


__all__ = [
    "DISABLED_PROVIDER",
    "VoiceTranscribeData",
    "VoiceTranscribeIn",
    "asr_configured",
    "transcribe",
]