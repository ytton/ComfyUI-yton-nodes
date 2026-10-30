"""Final and first-stage canvas dimensions for H3 generators."""

import math

UPSCALE_MODEL = "h3_upscaler_lms_v0.1.safetensors"

FILM_MODEL = "h3_clean_latent_upscaler_film_epoch200.safetensors"


def sampling_dimensions(width, height, sampling_mode, sampling_plan="tr", first_pass_scale=0.5):
    """Return target and low-stage dimensions; the target never means low-stage size."""
    if sampling_mode not in ("单采", "二采"):
        raise ValueError("采样模式请选择单采或二采。")
    width, height = int(width), int(height)
    if min(width, height) < 32 or width % 32 or height % 32:
        raise ValueError("最终宽高必须为不小于 32 的 32 像素倍数。")
    if sampling_mode == "单采":
        return width, height, width, height
    if sampling_plan == "selflift":
        return width, height, width, height
    if sampling_plan == "traditional":
        if not math.isfinite(first_pass_scale) or not 0.25 <= first_pass_scale <= 1.0:
            raise ValueError("首采比例必须在 0.25–1 之间。")
        return width, height, max(32, round(width * first_pass_scale / 32) * 32), max(32, round(height * first_pass_scale / 32) * 32)
    if sampling_plan != "tr":
        raise ValueError("未知的 H3 二采方案。")
    # H3's half-size canvas also needs a 32px boundary.
    if width % 64 or height % 64:
        raise ValueError("Film 2× 的最终宽高必须为 64 的倍数，例如 1920×1088 或 1344×768；首采固定为一半。")
    return width, height, width // 2, height // 2
