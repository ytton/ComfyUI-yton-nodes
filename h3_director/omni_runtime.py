"""A grouped H3 generation node, expanded by ComfyUI into existing nodes."""
import math

import comfy.samplers
from comfy_execution.graph_utils import GraphBuilder


class YtonH3OmniGenerate:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model_loader": ("FAST_MODEL_LOADER", {"rawLink": True}),
            "prompt": ("STRING", {"default": "", "multiline": True}),
            "width": ("INT", {"default": 1344, "min": 32, "max": 16384, "step": 32}),
            "height": ("INT", {"default": 768, "min": 32, "max": 16384, "step": 32}),
            "duration": ("FLOAT", {"default": 5.0, "min": 0.21, "max": 149.66, "step": 0.1,
                "tooltip": "采样总时长，包含续段会裁去的画面上下文。"}),
            "ref_image_size": (["match", "max"], {"default": "match"}),
            "steps": ("INT", {"default": 4, "min": 1, "max": 1000,
                "tooltip": "常规主采样的步数；轻量精修取该调度的最后一步。外部 Sigma 接入时，主采样步数由外部时间表决定。"}),
            "sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"default": "euler"}),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS, {"default": "simple"}),
            "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "latent_path": ("STRING", {"default": "h3_context/全能参考"}),
            "clip_index": ("INT", {"default": 1, "min": 1, "max": 9999,
                "tooltip": "第1段不读取上下文；第N段读取N−1，重抽覆盖当前段的 latent。"}),
            "context_length": ([22, 5, 39, 56], {"default": 22}),
            "audio_context_length": ("INT", {"default": 18, "min": 0, "max": 240,
                "tooltip": "独立于画面窗口，推荐18帧；0跟随画面窗口。"}),
            "use_refine": ("BOOLEAN", {"default": True,
                "tooltip": "实验性：额外精修1步，保留上下文画面，音频沿用主采样结果。关闭后不运行精修采样器。"}),
            "join_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.5, "step": 0.05,
                "tooltip": "实验性接缝匹配；0关闭。"}),
            "tail_strength": ("FLOAT", {"default": 0.5, "min": -0.9, "max": 3.0, "step": 0.05,
                "tooltip": "实验性 Sigma 尾段调整；0保留输入时间表。"}),
        }, "optional": {
            "image": ("IMAGE", {"rawLink": True}),
            "video": ("VIDEO", {"rawLink": True}),
            "audio": ("AUDIO", {"rawLink": True}),
            "sigmas": ("SIGMAS", {"rawLink": True,
                "tooltip": "连接即使用外部 Sigma；未连接时使用常规调度。"}),
        }}

    RETURN_TYPES = ("VIDEO", "LATENT", "STRING")
    RETURN_NAMES = ("video", "av_latent", "latent_path")
    FUNCTION = "generate"
    CATEGORY = "yton-nodes/MiniMax H3"
    OUTPUT_NODE = True
    DESCRIPTION = "全模态生成，原生 AV latent 续接；Sigma 可选输入。原生控件按生成、采样、种子、上下文分组，可直接连线控制。"

    def generate(self, model_loader, prompt, width, height, duration, ref_image_size,
                 steps, sampler_name, scheduler, denoise, seed, latent_path, clip_index,
                 context_length, audio_context_length, use_refine, join_strength, tail_strength,
                 image=None, video=None, audio=None, sigmas=None):
        graph = GraphBuilder()
        model = graph.node("fast modelFromLoader", id="models", **{"模型加载器": model_loader})
        length = 5 + 17 * max(0, math.floor((duration * 24 - 5) / 17 + 0.5))
        reference = graph.node("YtonMiniMaxH3ReferenceToVideo", id="reference",
            clip=model.out(1), vae=model.out(2), audio_vae=model.out(3), prompt=prompt,
            width=width, height=height, length=length, ref_image_size=ref_image_size)
        for name, link in [("image", image), ("video", video), ("audio", audio)]:
            reference.set_input(name, link)
        previous_index = clip_index - 1
        previous = graph.node("YuanH3NikoLoadLatent", id="previous", latent_path=latent_path,
            clip_index=previous_index, stock_format=False, folder="output")
        context = graph.node("YuanH3NikoMotionContext", id="context", conditioning=reference.out(0),
            vae=model.out(2), latent=reference.out(1), context_latent=previous.out(0),
            context_length=int(context_length), audio_context_length=audio_context_length)
        schedule = graph.node("BasicScheduler", id="schedule", model=model.out(0),
            scheduler=scheduler, steps=steps, denoise=denoise)
        tail = graph.node("MiniMaxH3SigmasTail", id="tail", sigmas=sigmas if sigmas is not None else schedule.out(0),
            tail_steps=3, strength=tail_strength)
        noise = graph.node("RandomNoise", id="noise", noise_seed=seed)
        guider = graph.node("BasicGuider", id="guider", model=model.out(0), conditioning=context.out(0))
        sampler = graph.node("KSamplerSelect", id="sampler", sampler_name=sampler_name)
        main = graph.node("SamplerCustomAdvanced", id="main", noise=noise.out(0), guider=guider.out(0),
            sampler=sampler.out(0), sigmas=tail.out(0), latent_image=reference.out(1))
        final = main.out(0)
        if use_refine:
            split = graph.node("SplitSigmas", id="refine_sigmas", sigmas=schedule.out(0), step=steps - 1)
            refine_noise = graph.node("RandomNoise", id="refine_noise", noise_seed=(seed + 1) % (1 << 64))
            plain = graph.node("BasicGuider", id="refine_guider", model=model.out(0), conditioning=reference.out(0))
            refined = graph.node("SamplerCustomAdvanced", id="refine", noise=refine_noise.out(0),
                guider=plain.out(0), sampler=sampler.out(0), sigmas=split.out(1), latent_image=main.out(0))
            final = graph.node("MiniMaxH3RefineBlend", id="blend", original=main.out(0), refined=refined.out(0),
                hold_frames=context.out(1), blend_frames=22, audio="original", use_refine=True,
                clip_index=previous_index).out(0)
        matched = graph.node("MiniMaxH3JoinMatch", id="join", samples=final, context_latent=previous.out(0),
            strength=join_strength, context_length=context.out(1), min_excess=1.5, match_spread=True,
            min_excess_spread=1.5, match_detail=True, min_excess_detail=1.5, tuning="auto")
        frames = graph.node("VAEDecode", id="frames", samples=matched.out(0), vae=model.out(2))
        sound = graph.node("VAEDecodeAudio", id="sound", samples=matched.out(0), vae=model.out(3))
        trimmed = graph.node("YuanH3NikoMotionContextTrim", id="trim", images=frames.out(0), audio=sound.out(0),
            trim_frames=context.out(1), fps=24.0, match_tail=True)
        video_result = graph.node("CreateVideo", id="video", images=trimmed.out(0), audio=trimmed.out(1), fps=24.0)
        ordered = graph.node("ImpactExecutionOrderController", id="ready", signal=video_result.out(0), value=matched.out(0))
        saved = graph.node("YuanH3NikoSaveLatent", id="save", latent=ordered.out(1),
            filename_prefix=latent_path.rstrip("/\\") + "/clip", clip_index=clip_index)
        return {"result": (video_result.out(0), matched.out(0), saved.out(0)), "expand": graph.finalize()}


NODE_CLASS_MAPPINGS = {"YtonH3OmniGenerate": YtonH3OmniGenerate}
NODE_DISPLAY_NAME_MAPPINGS = {"YtonH3OmniGenerate": "H3 全模态生成"}
