"""向后兼容 shim：腾讯云视觉客户端已迁至 `tencent_vision.py`（阿里云见 `aliyun_vision.py`）。

保留本模块仅为不破坏既有导入路径（`from app.ai.vision import TencentVisionClient`）。
"""

from .tencent_vision import TencentVisionClient, tc3_signature

__all__ = ["TencentVisionClient", "tc3_signature"]
