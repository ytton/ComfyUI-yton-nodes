"""Sampling-plan contracts for the VIDEO-context generator."""

import math

TRADITIONAL = "传统二采"
SELFLIFT = "SelfLift Progressive Sampler (MiniMax H3)"
FILM = "Film 2×"
SAMPLING_PLANS = (TRADITIONAL, SELFLIFT, FILM)
FILM_MODEL = "h3_clean_latent_upscaler_film_epoch200.safetensors"


def sampling_dimensions(width, height, sampling_mode, sampling_plan, first_pass_scale):
    """Return target and low-stage dimensions; the target never means low-stage size."""
    if sampling_mode not in ("单采", "二采"):
        raise ValueError("采样模式请选择单采或二采。")
    if sampling_plan not in SAMPLING_PLANS:
        raise ValueError("请选择传统二采、SelfLift 或 Film 2×。")
    width, height = int(width), int(height)
    if min(width, height) < 32 or width % 32 or height % 32:
        raise ValueError("最终宽高必须为不小于 32 的 32 像素倍数。")
    if sampling_mode == "单采":
        return width, height, width, height
    if sampling_plan == FILM:
        # H3's half-size canvas also needs a 32px boundary. Do not silently
        # round the requested final size to a different output resolution.
        if width % 64 or height % 64:
            raise ValueError("Film 2× 的最终宽高必须为 64 的倍数，例如 1920×1088 或 1344×768；首采固定为一半。")
        return width, height, width // 2, height // 2
    scale = float(first_pass_scale)
    minimum = 0.25 if sampling_plan == SELFLIFT else 0.125
    if not math.isfinite(scale) or not minimum <= scale <= 1.0:
        raise ValueError(f"当前方案的首采比例必须在 {minimum}～1.0 之间。")
    return (width, height, max(32, round(width * scale / 32) * 32),
            max(32, round(height * scale / 32) * 32))
