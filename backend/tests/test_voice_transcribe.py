"""语音转写端点测试（G4）：未配置 ASR 时明确降级。

契约 `/api/ai/voice-transcribe`（security 继承全局 bearerAuth）。
"""


async def test_voice_transcribe_disabled(db_client, authed):
    """无 ASR 配置 → HTTP 200 且 {text:"", provider:"disabled"}（不 500）。"""
    r = await db_client.post(
        "/api/ai/voice-transcribe",
        headers=authed["headers"],
        json={"audio_base64": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgA==", "format": "wav"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"] == {"text": "", "provider": "disabled"}


async def test_voice_transcribe_requires_auth(db_client):
    """未带 token → 401/1001（继承全局 bearerAuth）。"""
    r = await db_client.post(
        "/api/ai/voice-transcribe", json={"audio_base64": "AAAA", "format": "mp3"}
    )
    assert r.status_code == 401 and r.json()["code"] == 1001