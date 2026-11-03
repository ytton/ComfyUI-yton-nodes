"""Prompt, canvas, duration, and local references in one H3 preparation node."""

import math

import comfy.utils
from comfy_api.latest import io
from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo, align_frame_count
from .media_loader_node import MEDIA_SLOTS, YtonEasyMediaLoader, YtonVideoParser, media_fingerprint
from ..prompt_optimizer_media import media_content
from .resolution_node import H3_MP_VALUES, H3_RATIO_PRESETS, YtonResolutionSelector, resolve_aspect_ratio

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
                io.Float.Input("duration", default=5, min=0.1, max=150, step=0.01, round=False),
                *media,
            ],
            outputs=[io.Conditioning.Output(display_name="正向条件"), io.Latent.Output(display_name="AV latent"),
                     io.Int.Output(display_name="宽度"), io.Int.Output(display_name="高度")],
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
        return io.NodeOutput(*output.result, width, height)


class YtonH3VideoConfig(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="YtonH3VideoConfig",
            display_name="H3 视频生成配置器",
            category="yton-nodes/MiniMax H3",
            description="左侧设置生成参数，右侧编辑提示词。图片、视频、音频列表可连接用于比例识别和 LLM 优化；媒体请从加载器直接连接生成节点。",
            is_input_list=True,
            is_output_node=True,
            inputs=[
                io.String.Input("prompt", default="", multiline=True, dynamic_prompts=True),
                io.Boolean.Input("optimize_prompt", default=False, socketless=True),
                io.Combo.Input("resolution", options=RESOLUTIONS, default="768p",
                    extra_dict={"yton_presets": {f"{ratio}|{preset}": list(size)
                                for (ratio, preset), size in H3_RATIO_PRESETS.items() if preset in RESOLUTIONS},
                                "yton_h3_multipliers": {preset: H3_MP_VALUES[preset] for preset in RESOLUTIONS}}),
                io.Combo.Input("aspect_ratio", options=["auto", *ASPECT_RATIOS], default="16:9"),
                io.Combo.Input("ref_image_size", options=["max", "match", "自定义"], default="match"),
                io.Float.Input("ref_scale", default=0.5, min=0.05, max=4, step=0.05,
                    tooltip="自定义模式按该倍率缩放原始参考图；可连接下游参考图缩放流程。"),
                io.Float.Input("duration", default=5, min=0.1, max=150, step=0.01, round=False),
                io.Image.Input("image", display_name="图片列表", optional=True, raw_link=True),
                io.Video.Input("video", display_name="视频列表", optional=True, raw_link=True),
                io.Audio.Input("audio", display_name="音频列表", optional=True, raw_link=True),
                io.Custom("YTON_LLM").Input("llm", display_name="LLM 连接器", optional=True, raw_link=True,
                    tooltip="开启运行时提示词优化后必需；优化时使用连接的图片、视频和音频素材。"),
            ],
            outputs=[
                io.String.Output(display_name="提示词"),
                io.Int.Output(display_name="宽度"),
                io.Int.Output(display_name="高度"),
                io.Int.Output(display_name="长度（帧数）"),
                io.Float.Output(display_name="实际时长（秒）"),
                io.String.Output(display_name="参考图尺寸"),
                io.Float.Output(display_name="参考图缩放比例"),
            ],
        )

    @classmethod
    def execute(cls, prompt, optimize_prompt, resolution, aspect_ratio, ref_image_size,
                ref_scale, duration, image=None, video=None, audio=None, llm=None):
        def scalar(value, default=None):
            if isinstance(value, list):
                return value[0] if value else default
            return default if value is None else value

        def as_list(value):
            if value is None:
                return []
            if isinstance(value, (list, tuple)):
                return list(value)
            return [value]

        prompt = scalar(prompt, "")
        optimize_prompt = bool(scalar(optimize_prompt, False))
        resolution = scalar(resolution)
        aspect_ratio = scalar(aspect_ratio)
        ref_image_size = scalar(ref_image_size)
        ref_scale = scalar(ref_scale)
        duration = scalar(duration)
        llm = scalar(llm)
        images = as_list(image)
        videos = as_list(video)
        audios = as_list(audio)
        first_image = next((item for item in images if item is not None), None)
        aspect_ratio = resolve_aspect_ratio(aspect_ratio, first_image)
        width, height, *_ = YtonResolutionSelector().get_resolution(
            "MiniMax H3 (Video)", aspect_ratio, resolution,
        )
        if ref_image_size not in ("max", "match", "自定义"):
            raise ValueError("参考图尺寸选项无效。")
        if not math.isfinite(ref_scale) or ref_scale <= 0:
            raise ValueError("参考图缩放比例需要大于 0。")
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("时长需要大于 0 秒。")
        frames = align_frame_count(max(5, math.ceil(duration * 24)))
        image_count = sum(int(item.shape[0]) if getattr(item, "ndim", 0) == 4 else 1
                          for item in images if item is not None)
        video_count = sum(item is not None for item in videos)
        audio_count = sum(item is not None for item in audios)
        if optimize_prompt:
            if llm is None:
                raise ValueError("请连接【LLM 通用连接器】后再优化提示词。")
            references = media_content(image=images, audio=audios, video=videos)
            prompt = llm.generate(
                f"请将用户要求整理成可直接用于 MiniMax H3 视频生成的提示词，结合已连接的图片、视频和音频参考。"
                f"保留并正确使用素材引用标签 <Picture N>、<Video N>、<Audio N>，不输出说明或代码块。\n"
                f"图片参考：{image_count} 张；视频参考：{video_count} 段；音频参考：{audio_count} 段。\n"
                f"用户原始提示词：\n{prompt}",
                system="你是视频生成提示词编写助手。准确落实用户要求，依据可见参考素材描述主体、动作、构图、场景和镜头。"
                       "依据音频参考描述可听见的语音、说话节奏与声音特征，不臆造无法确认的内容。"
                       "保留用户明确给出的内容，不虚构无法从素材判断的细节。只输出最终提示词。",
                media=references,
            ).strip()
            if not prompt:
                raise ValueError("LLM 返回了空提示词，请检查模型是否支持当前参考素材。")

        native_ref_size = ref_image_size
        if ref_image_size == "自定义":
            native_ref_size = "max"
        config_info = {"width": width, "height": height, "frames": frames, "seconds": frames / 24,
                       "aspect_ratio": aspect_ratio, "resolution": resolution}
        prompt_info = {"text": prompt, "optimized": optimize_prompt, "image_count": image_count,
                       "video_count": video_count, "audio_count": audio_count}
        return io.NodeOutput(prompt, width, height, frames, frames / 24, native_ref_size, ref_scale,
                             ui={"h3_video_config": [config_info], "h3_video_prompt": [prompt_info]})
