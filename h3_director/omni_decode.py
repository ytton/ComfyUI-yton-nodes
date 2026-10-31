"""Video decode choices shared by the three H3 generators."""

REFERENCE_DETAIL_MODE = "X2 VAE 解码 + 参考图增强"
DECODE_MODES = ["标准解码", "X2 VAE 解码", REFERENCE_DETAIL_MODE]
X2_VAE = "MiniMax-H3-X2-Detail-v1.safetensors"


def add_reference_detail(graph, images, mode, x2_vae_name, strength):
    if mode != REFERENCE_DETAIL_MODE or images is None:
        return images
    return graph.node("MiniMaxH3X2DetailedUpscale", id="reference_detail", images=images,
                      detail_vae=x2_vae_name, detail_strength=strength).out(0)


def add_video_decode(graph, samples, vae, mode="标准解码", x2_vae_name=X2_VAE,
                     tile_size=256, tile_overlap=64):
    if mode == "标准解码":
        return graph.node("VAEDecode", id="frames", samples=samples, vae=vae).out(0)
    if mode not in DECODE_MODES:
        raise ValueError("请选择标准解码、X2 VAE 解码或 X2 VAE 解码 + 参考图增强。")
    vae = graph.node("VAELoader", id="decode_vae", vae_name=x2_vae_name).out(0)
    return graph.node("MiniMaxH3VAEDecodeFast", id="frames", samples=samples, vae=vae,
        tiling=True, tile_size=tile_size, tile_overlap=tile_overlap, output_device="cpu",
        temporal_tiling=False, temporal_tile_frames=85, temporal_context_frames=39,
        seam_warning_threshold=0.02).out(0)
