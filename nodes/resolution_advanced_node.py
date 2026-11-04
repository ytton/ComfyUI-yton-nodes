"""Resolution controls with independently configurable ports and UI sections."""
import math
from math import gcd

from .resolution_node import YtonResolutionSelector, align_h3_dimension, resolve_aspect_ratio


class YtonResolutionSelectorAdvanced(YtonResolutionSelector):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["MiniMax H3 (Video)", "Normal (Standard Image/Video)"], {"default": "MiniMax H3 (Video)"}),
                "aspect_ratio": ("STRING", {"default": "16:9"}),
                "resolution": ("STRING", {"default": "1080p"}),
                "ui_config": ("STRING", {"default": "{}"}),
            },
            "optional": {
                "width": ("INT", {"default": 0, "min": 0, "max": 16384, "step": 1}),
                "height": ("INT", {"default": 0, "min": 0, "max": 16384, "step": 1}),
                "image": ("IMAGE", {"tooltip": "比例选择自动时，按图片宽高匹配最接近的预设比例；未连接图片时使用 16:9"}),
            },
        }

    def get_resolution(self, mode, aspect_ratio, resolution, ui_config="{}", width=0, height=0, image=None):
        aspect_ratio = resolve_aspect_ratio(aspect_ratio, image)
        try:
            parts = [float(value) for value in aspect_ratio.strip().split(":")]
            if len(parts) != 2 or any(not math.isfinite(value) or value <= 0 for value in parts):
                raise ValueError()
        except (ValueError, AttributeError, TypeError):
            raise ValueError("画面比例必须是有效的正数比例，例如 16:9 或 3:4") from None
        aspect_ratio = aspect_ratio.strip()
        allowed = ("320p", "480p", "540p", "640p", "720p", "768p", "944p", "1024p", "1080p", "2K", "4K") if "H3" in mode else ("480p", "540p", "640p", "720p", "1080p", "2K", "2.5K", "4K", "6K")
        if resolution not in allowed:
            raise ValueError(f"当前模式不支持分辨率：{resolution}")
        if width < 0 or height < 0 or width > 16384 or height > 16384:
            raise ValueError("宽度和高度需要在 0～16384 之间；0 表示根据预设或比例计算")
        result = super().get_resolution(mode, aspect_ratio, resolution)
        if not width and not height:
            return result
        ratio = parts[0] / parts[1]
        w = width or max(1, round(height * ratio))
        h = height or max(1, round(width / ratio))
        if "H3" in mode:
            w, h = align_h3_dimension(w), align_h3_dimension(h)
        divisor = gcd(w, h)
        return (w, h, f"{w // divisor}:{h // divisor}", max(w, h), min(w, h), result[5], "custom")
