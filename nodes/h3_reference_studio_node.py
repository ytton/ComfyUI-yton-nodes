"""Prompt, canvas, duration, and local references in one H3 preparation node."""

import math

import comfy.utils
from comfy_api.latest import io
from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo, align_frame_count

from .media_loader_node import MEDIA_SLOTS, YtonEasyMediaLoader, YtonVideoParser, media_fingerprint
from .resolution_node import H3_MP_VALUES, H3_RATIO_PRESETS, YtonResolutionSelector

ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "2:3", "3:2", "21:9"]
RESOLUTIONS = ["320p", "480p", "540p", "640p", "720p", "768p", "944p", "1024p", "1080p"]


class YtonH3ReferenceStudio(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        media = []
        for kind, count in MEDIA_SLOTS.items():
            for index in range(1, count + 1):
                media.extend([
                    io.String.Input(f"{kind}_{index}", default="", socketless=True),
                    io.Boolean.Input(f"disable_{kind}_{index}", default=False, socketless=True),
                ])
        return io.Schema(
            node_id="YtonH3ReferenceStudio",
            display_name="H3 参考视频工作台",
            category="yton-nodes/MiniMax H3",
            description="提示词、画幅、时长与参考媒体集中设置，输出 H3 正向条件和 AV latent，连接后续采样器。",
            search_aliases=["H3", "参考生成", "媒体", "一体化"],
            inputs=[
                io.Clip.Input("clip", display_name="文本编码器"),
                io.Vae.Input("vae", display_name="视频 VAE", optional=True),
                io.Vae.Input("audio_vae", display_name="音频 VAE", optional=True),
                io.String.Input("prompt", default="", multiline=True, dynamic_prompts=True),
                io.Combo.Input("aspect_ratio", options=["auto", *ASPECT_RATIOS], default="16:9"),
                io.Combo.Input("resolution", options=RESOLUTIONS, default="768p",
                    extra_dict={"yton_presets": {f"{ratio}|{preset}": list(size)
                                for (ratio, preset), size in H3_RATIO_PRESETS.items() if preset in RESOLUTIONS},
                                "yton_h3_multipliers": {preset: H3_MP_VALUES[preset] for preset in RESOLUTIONS}}),
                io.Combo.Input("ref_image_size", options=["max", "match", "自定义"], default="match"),
                io.Float.Input("ref_scale", default=0.5, min=0.05, max=4, step=0.05,
                    tooltip="以 match 尺寸为基准的宽高倍率；不会放大超过原图，仍遵循 H3 原生参考图尺寸上限。"),
                io.Float.Input("duration", default=5, min=0.1, max=150, step=0.5),
                *media,
            ],
            outputs=[io.Conditioning.Output(display_name="正向条件"), io.Latent.Output(display_name="AV latent"),
                     io.Int.Output(display_name="宽度"), io.Int.Output(display_name="高度"),
                     io.Int.Output(display_name="帧数")],
        )

    @classmethod
    def fingerprint_inputs(cls, **inputs):
        return media_fingerprint(**inputs)

    @classmethod
    def execute(cls, clip, prompt, aspect_ratio, resolution,
                ref_image_size, ref_scale, duration, vae=None, audio_vae=None, **slots):
        images, videos, audios = YtonEasyMediaLoader().load_media(**slots)
        first_image = next((image for image in images if image is not None), None)
        if aspect_ratio == "auto":
            image_ratio = first_image.shape[2] / first_image.shape[1] if first_image is not None else 16 / 9
            def distance(ratio):
                w, h = map(int, ratio.split(":"))
                return abs(math.log(image_ratio / (w / h)))
            aspect_ratio = min(ASPECT_RATIOS, key=distance)
        width, height, *_ = YtonResolutionSelector().get_resolution(
            "MiniMax H3 (Video)", aspect_ratio, resolution,
        )
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("时长需要大于 0 秒。")
        length = align_frame_count(max(5, math.ceil(duration * 24)))
        if ref_image_size == "自定义":
            if not math.isfinite(ref_scale) or ref_scale <= 0:
                raise ValueError("参考图缩放比例需要大于 0。")
            scaled = []
            for image in images:
                if image is None:
                    scaled.append(None)
                    continue
                h, w = image.shape[1:3]
                scale = min(1.0, min(1.0, math.sqrt(width * height / (w * h))) * ref_scale)
                tw, th = (max(32, round(side * scale / 32) * 32) for side in (w, h))
                scaled.append(comfy.utils.common_upscale(image.movedim(-1, 1), tw, th,
                    "lanczos", "disabled").movedim(1, -1))
            images = scaled
            ref_image_size = "max"
        ref_videos, ref_video_audios = {}, {}
        for index, video in enumerate(videos, 1):
            frames, _, soundtrack, _ = YtonVideoParser().parse_video(video, force_rate=24)
            ref_videos[f"ref_video_{index}"] = frames
            ref_video_audios[f"ref_video_audio_{index}"] = soundtrack
        output = MiniMaxH3ReferenceToVideo.execute(
            clip=clip, prompt=prompt, width=width, height=height, length=length,
            ref_image_size=ref_image_size, vae=vae, audio_vae=audio_vae,
            ref_images={f"ref_image_{i}": image for i, image in enumerate(images, 1)},
            ref_videos=ref_videos, ref_video_audios=ref_video_audios,
            ref_audios={f"ref_audio_{i}": audio for i, audio in enumerate(audios, 1)},
        )
        return io.NodeOutput(*output.result, width, height, length)
