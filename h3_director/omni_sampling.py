"""Film 2× dimensions for the VIDEO-context generator."""

FILM_MODEL = "h3_clean_latent_upscaler_film_epoch200.safetensors"


def sampling_dimensions(width, height, sampling_mode):
    """Return target and low-stage dimensions; the target never means low-stage size."""
    if sampling_mode not in ("单采", "二采"):
        raise ValueError("采样模式请选择单采或二采。")
    width, height = int(width), int(height)
    if min(width, height) < 32 or width % 32 or height % 32:
        raise ValueError("最终宽高必须为不小于 32 的 32 像素倍数。")
    if sampling_mode == "单采":
        return width, height, width, height
    # H3's half-size canvas also needs a 32px boundary.
    if width % 64 or height % 64:
        raise ValueError("Film 2× 的最终宽高必须为 64 的倍数，例如 1920×1088 或 1344×768；首采固定为一半。")
    return width, height, width // 2, height // 2
