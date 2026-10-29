"""Single/two-pass H3 sampling with the 1029 workflow's latent continuation."""
import math

from comfy_execution.graph_utils import GraphBuilder

from .omni_context import CONTEXT_FRAMES, context_name
from .omni_face import add_face_refinement


def build_omni_graph(model_loader, prompt, width, height, mode, duration, ref_image_size,
                     sampling_mode, steps, sampler_name, scheduler, denoise, seed,
                     first_pass_scale, upscale_model, second_sampler, second_sigma_values,
                     latent_path, clip_index, face_refine, face_count, face_steps, face_denoise,
                     face_detector, face_reverse, face_large_strength, face_fallback_detector,
                     face_seed, image=None, video=None, audio=None,
                     sigmas=None, second_sigmas=None, context_path="", second_model=None,
                     face_model=None, face_sigmas=None):
    if sampling_mode not in ("单采", "二采"):
        raise ValueError("采样模式请选择单采或二采。")
    graph = GraphBuilder()
    models = graph.node("fast modelFromLoader", id="models", **{"模型加载器": model_loader})
    two_pass = sampling_mode == "二采"
    main_width = max(32, round(width * first_pass_scale / 32) * 32) if two_pass else width
    main_height = max(32, round(height * first_pass_scale / 32) * 32) if two_pass else height
    previous_path = context_path or (context_name(latent_path, clip_index - 1) if clip_index > 1 else "")
    overlap = CONTEXT_FRAMES if previous_path else 0
    source_images = source_audio = source_video = None
    if mode == "复刻模式":
        if video is None:
            raise ValueError("复刻模式需要传入至少一个视频，时长取第一个视频。")
        plan = graph.node("YtonH3ReplicaPlan", id="replica", video=video, context_frames=overlap)
        length, trim_frames = plan.out(0), plan.out(1)
    elif mode == "普通模式":
        if video is not None:
            plan = graph.node("YtonH3SegmentPlan", id="segment", duration=duration,
                clip_index=clip_index, context_frames=overlap)
            length, trim_frames = plan.out(0), plan.out(1)
            source_start = plan.out(2)
        else:
            length = 5 + 17 * max(0, math.floor((duration * 24 + overlap - 5) / 17 + 0.5))
            length = max(39 if overlap else 5, length)
            trim_frames = length - max(1, math.floor(float(duration) * 24 + 0.5))
            source_start = None
    else:
        raise ValueError("请选择普通模式或复刻模式。")
    previous = None
    if previous_path:
        previous = graph.node("YtonH3LoadOmniContext", id="previous", context_path=previous_path,
            main_width=main_width, main_height=main_height, width=width, height=height)
    if video is not None and mode == "普通模式":
        components = graph.node("GetVideoComponents", id="source_components", video=video)
        source_images = graph.node("GetImageRangeFromBatch", id="source_images",
            images=components.out(0), start_index=source_start, num_frames=length).out(0)
        start_seconds = graph.node("ComfyMathExpression", id="source_start_seconds",
            expression="a / 24", **{"values.a": source_start}).out(0)
        source_duration = graph.node("ComfyMathExpression", id="source_duration",
            expression="a / 24", **{"values.a": length}).out(0)
        source_audio = graph.node("TrimAudioDuration", id="source_audio", audio=components.out(1),
            start_index=start_seconds, duration=source_duration).out(0)
        source_video = graph.node("CreateVideo", id="source_video", images=source_images,
            audio=source_audio, fps=components.out(2)).out(0)

    reference = graph.node("YtonMiniMaxH3ReferenceToVideo", id="reference",
        clip=models.out(1), vae=models.out(2), audio_vae=models.out(3), prompt=prompt,
        width=main_width, height=main_height, length=length, ref_image_size=ref_image_size)
    for name, link in (("image", image), ("video", source_video if source_video is not None else video),
                       ("audio", audio if source_video is None else None)):
        if link is not None:
            reference.set_input(name, link)
    latent = reference.out(1)
    if previous is not None:
        latent = graph.node("MiniMaxH3LatentHeadReplace", id="main_context",
            latent_tail=previous.out(0), latent_base=latent, replace_frames=CONTEXT_FRAMES,
            head_mask_strength=0.0, apply_mask=True, replace_audio=False).out(0)
    schedule = sigmas
    if schedule is None:
        schedule = graph.node("BasicScheduler", id="schedule", model=models.out(0),
            scheduler=scheduler, steps=steps, denoise=denoise).out(0)
    noise = graph.node("RandomNoise", id="noise", noise_seed=seed)
    conditioning = reference.out(0)
    if source_images is not None:
        conditioning = graph.node("MiniMaxH3AddGuide", id="source_guide", positive=conditioning,
            latent=reference.out(1), vae=models.out(2), image=source_images, frame_idx=0).out(0)
    guider = graph.node("BasicGuider", id="guider", model=models.out(0), conditioning=conditioning)
    sampler = graph.node("KSamplerSelect", id="sampler", sampler_name=sampler_name)
    main = graph.node("SamplerCustomAdvanced", id="main", noise=noise.out(0), guider=guider.out(0),
        sampler=sampler.out(0), sigmas=schedule, latent_image=latent)
    final = main.out(0)
    if two_pass:
        second_model = models.out(0) if second_model is None else second_model
        high_reference = graph.node("YtonMiniMaxH3ReferenceToVideo", id="high_reference",
            clip=models.out(1), vae=models.out(2), audio_vae=models.out(3),
            prompt="Enhance this video with sharp, crisp details while preserving a natural photorealistic appearance.",
            width=width, height=height, length=length, ref_image_size=ref_image_size)
        if image is not None:
            high_reference.set_input("image", image)
        if source_video is not None:
            high_reference.set_input("video", source_video)
        split = graph.node("LTXVSeparateAVLatent", id="split_main", av_latent=main.out(0))
        upscaled = graph.node("MinimaxH3LatentUpscaler3D", id="upscale", latent=split.out(0),
            model_name=upscale_model, mode="target dimensions", **{"mode.width": width, "mode.height": height},
            align=32, enable_temporal_chunking=True, force_unload=True, device="cuda", precision="fp16")
        latent = graph.node("LTXVConcatAVLatent", id="high_av",
            video_latent=upscaled.out(0), audio_latent=split.out(1)).out(0)
        if previous is not None:
            latent = graph.node("MiniMaxH3LatentHeadReplace", id="high_context",
                latent_tail=previous.out(1), latent_base=latent, replace_frames=CONTEXT_FRAMES,
                head_mask_strength=0.0, apply_mask=True, replace_audio=False).out(0)
        high_schedule = second_sigmas
        if high_schedule is None:
            high_schedule = graph.node("ManualSigmas", id="high_sigmas", sigmas=second_sigma_values).out(0)
        high_guider = graph.node("BasicGuider", id="high_guider",
            model=second_model, conditioning=high_reference.out(0))
        high_noise = graph.node("RandomNoise", id="high_noise", noise_seed=seed)
        high_sampler = graph.node("KSamplerSelect", id="high_sampler", sampler_name=second_sampler)
        final = graph.node("SamplerCustomAdvanced", id="high_sample", noise=high_noise.out(0),
            guider=high_guider.out(0), sampler=high_sampler.out(0), sigmas=high_schedule, latent_image=latent).out(0)
    frames = graph.node("VAEDecode", id="frames", samples=final, vae=models.out(2)).out(0)
    sound = graph.node("VAEDecodeAudio", id="sound", samples=final, vae=models.out(3)).out(0)
    if face_refine:
        face_model = models.out(0) if face_model is None else face_model
        frames = add_face_refinement(graph, frames, final, face_model, models.out(1), models.out(2), models.out(3), image, prompt, ref_image_size,
                                     face_count, face_steps, face_denoise, face_detector, face_reverse,
                                     face_seed, face_sigmas, face_large_strength, face_fallback_detector)
    trimmed = graph.node("YuanH3NikoMotionContextTrim", id="trim", images=frames, audio=sound,
        trim_frames=trim_frames, fps=24.0, match_tail=True)
    frames = trimmed.out(0)
    if previous is not None:
        joined = graph.node("H3ColorMatchSeamlessJoin", id="seam", video_A=previous.out(2), video_B=frames,
            overlap_frames=0, use_gaussian_blur=False, use_luma_affine=False,
            use_fade_transition=True, detect_window=4, fade_frames=5)
        frames = graph.node("GetImageRangeFromBatch", id="new_frames", images=joined.out(0),
            start_index=previous.out(3), num_frames=4096).out(0)
    video_result = graph.node("CreateVideo", id="video", images=frames, audio=trimmed.out(1), fps=24.0)
    saved = graph.node("YtonH3SaveOmniContext", id="save_context", video=video_result.out(0),
        main_latent=main.out(0), final_latent=final, sampling_mode=sampling_mode,
        latent_path=latent_path, clip_index=clip_index)
    return {"result": (video_result.out(0), final, saved.out(0)), "expand": graph.finalize()}
