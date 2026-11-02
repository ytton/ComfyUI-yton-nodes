"""H3 generation with a previous VIDEO as the continuation guide."""

import math

from comfy_execution.graph_utils import GraphBuilder

from .omni_face import add_face_refinement
from .omni_runtime import plan_context_length
from .omni_sampling import FILM_MODEL, UPSCALE_MODEL, sampling_dimensions

CONTEXT_FRAMES = 22


def _guide_from_previous(graph, previous, prefix, noise_strength):
    """前 21 帧按指定强度加噪，最后一帧保持原样。"""
    first = graph.node("GetImageRangeFromBatch", id=prefix + "context_first",
                       images=previous.out(0), start_index=0, num_frames=CONTEXT_FRAMES - 1).out(0)
    last = graph.node("GetImageRangeFromBatch", id=prefix + "context_last",
                      images=previous.out(0), start_index=CONTEXT_FRAMES - 1, num_frames=1).out(0)
    first_noisy = graph.node("ImageAddNoise", id=prefix + "context_first_noise",
                             image=first, seed=0, strength=noise_strength).out(0)
    last_exact = graph.node("ImageAddNoise", id=prefix + "context_last_exact",
                            image=last, seed=0, strength=0.0).out(0)
    guide = graph.node("ImageBatchMulti", id=prefix + "context_guide",
                       inputcount=2, image_1=first_noisy, image_2=last_exact).out(0)
    return guide


def _add_guide(graph, positive, latent, vae, audio_vae, image, audio, prefix):
    guide = graph.node("MiniMaxH3AddGuide", id=prefix, positive=positive, latent=latent,
                       vae=vae, audio_vae=audio_vae, image=image, audio=audio, frame_idx=0)
    return graph.node("MiniMaxH3AudioGuideFeather", id=prefix + "_audio_feather",
                      positive=guide.out(0), audio_feather_ticks=256).out(0)


def _color_match(graph, frames, previous, prefix, strength, target_index=0):
    """用上一段末帧匹配本段颜色，整段共用首帧新增画面的变换。"""
    if strength == 0:
        return frames
    reference = graph.node("GetImageRangeFromBatch", id=prefix + "reference_frame",
                           images=previous.out(0), start_index=CONTEXT_FRAMES - 1,
                           num_frames=1).out(0)
    return graph.node("ColorTransfer", id=prefix + "color_match", image_target=frames,
                      image_ref=reference, method="mkl_lab",
                      source_stats="target_frame", **{"source_stats.target_index": target_index},
                      strength=strength).out(0)


def build_video_context_graph(model, clip, vae, audio_vae, prompt, width, height, mode, duration, ref_image_size,
                              sampling_mode, steps, sampler_name, scheduler, denoise, seed,
                              face_refine, face_count, face_reverse, image=None, video=None, audio=None,
                              sigmas=None, previous_video=None, second_model=None,
                              face_model=None, face_sigmas=None, enable_context=False,
                              context_auto_extend=True,
                              debug_keep_context=False,
                              context_noise_strength=0.1, context_color_strength=0.75,
                              film_model=FILM_MODEL, film_method="learned model",
                              film_audio_denoise=0.0, film_noise_resample="independent", film_match_stats=0.0,
                              second_steps=4, second_sigma_start=0.4, second_rho=7.0, second_ff_chunks="8",
                              sampling_plan="tr", first_pass_scale=0.5, upscale_model=UPSCALE_MODEL,
                              second_sampler="euler", second_sigma_values="",
                              selflift_transition_step=2, selflift_rho=0.0, selflift_w_min=0.5, selflift_w_max=1.0,
                              selflift_highres_tiling=False, selflift_highres_tiles="auto"):
    width, height, main_width, main_height = sampling_dimensions(
        width, height, sampling_mode, sampling_plan, first_pass_scale)
    if not enable_context:
        previous_video = None
    graph = GraphBuilder()
    two_pass = sampling_mode == "二采"
    overlap = CONTEXT_FRAMES if previous_video is not None else 0
    keep_context = debug_keep_context and overlap > 0

    if mode == "复刻模式":
        if video is None:
            raise ValueError("复刻模式需要传入至少一个视频，时长取第一个视频。")
        plan = graph.node("YtonH3ReplicaPlan", id="replica", video=video, context_frames=overlap,
                          context_auto_extend=context_auto_extend)
        length = plan.out(0)
        head_trim_frames, tail_trim_frames = plan.out(1), plan.out(2)
    elif mode == "普通模式":
        visible_frames = max(1, math.floor(float(duration) * 24 + 0.5))
        length, head_trim_frames, tail_trim_frames = plan_context_length(
            visible_frames, overlap, context_auto_extend)
    else:
        raise ValueError("请选择普通模式或复刻模式。")

    previous = None
    if previous_video is not None:
        previous = graph.node("YtonH3VideoTail", id="previous", video=previous_video)

    reference = graph.node("YtonMiniMaxH3ReferenceToVideo", id="reference",
                           clip=clip, vae=vae, audio_vae=audio_vae,
                           prompt=prompt, width=main_width, height=main_height,
                           length=length, ref_image_size=ref_image_size)
    for name, link in (("image", image), ("video", video), ("audio", audio)):
        if link is not None:
            reference.set_input(name, link)

    conditioning = reference.out(0)
    if previous is not None:
        guide_images = _guide_from_previous(graph, previous, "main_ctx_", context_noise_strength)
        conditioning = _add_guide(graph, conditioning, reference.out(1), vae, audio_vae,
                                   guide_images, previous.out(1), "main_context_add_guide")

    high_conditioning = None
    if two_pass and sampling_plan == "traditional":
        high_reference = graph.node("YtonMiniMaxH3ReferenceToVideo", id="high_reference",
                                   clip=clip, vae=vae, audio_vae=audio_vae,
                                   prompt=prompt, width=width, height=height, length=length,
                                   ref_image_size=ref_image_size)
        for name, link in (("image", image), ("video", video), ("audio", audio)):
            if link is not None:
                high_reference.set_input(name, link)
        high_conditioning = high_reference.out(0)
        if previous is not None:
            high_conditioning = _add_guide(graph, high_conditioning, high_reference.out(1),
                                           vae, audio_vae, guide_images, previous.out(1),
                                           "high_context_add_guide")

    preparation = graph.node("YtonH3PrepareSampling", id="prepare_sampling",
                             model=model, conditioning=conditioning, clip=clip)
    if high_conditioning is not None:
        preparation.set_input("additional_conditioning", high_conditioning)
    main_model = preparation.out(0)

    schedule = sigmas
    if schedule is None:
        schedule = graph.node("BasicScheduler", id="schedule", model=model,
                              scheduler=scheduler, steps=steps, denoise=denoise).out(0)
    high_model = model if second_model is None else second_model
    if two_pass and second_ff_chunks != "沿用模型":
        high_model = graph.node("MiniMaxChunkFeedForward", id="high_ff_chunks", model=high_model,
                                chunks=int(second_ff_chunks), seq_threshold=4096).out(0)
    if two_pass and sampling_plan == "selflift":
        if sampler_name != "euler":
            raise ValueError("SelfLift 仅支持标准 Euler 采样器。")
        if sigmas is None and not 1 <= selflift_transition_step < steps:
            raise ValueError("SelfLift 切换步数必须至少为 1，并小于主采总步数。")
        if not 0.25 <= first_pass_scale <= 1.0:
            raise ValueError("SelfLift 首采比例必须在 0.25–1 之间。")
        if not 0 <= selflift_w_min <= selflift_w_max <= 1:
            raise ValueError("SelfLift 校正权重必须满足 0 ≤ 下限 ≤ 上限 ≤ 1。")
        if upscale_model == "none" and selflift_rho == 0:
            raise ValueError("SelfLift 未选择超分模型时，校正范围 rho 必须大于 0。")
        negative = graph.node("ConditioningZeroOut", id="selflift_negative", conditioning=conditioning)
        sampler = graph.node("KSamplerSelect", id="sampler", sampler_name="euler")
        high_model = graph.node("YtonH3PrepareSampling", id="high_prepare_sampling",
                                model=high_model, clip=clip, conditioning=conditioning).out(0)
        final = graph.node("SelfLiftH3Sampler", id="main", model=main_model, model_hires=high_model,
                           positive=conditioning, negative=negative.out(0), vae=vae,
                           latent_image=reference.out(1), sampler=sampler.out(0), sigmas=schedule,
                           seed=seed, cfg=1.0, transition_step=selflift_transition_step, lowres_scale=first_pass_scale,
                           rho=selflift_rho, w_min=selflift_w_min, w_max=selflift_w_max,
                           upscaler_model=upscale_model, highres_tiling=selflift_highres_tiling,
                           highres_tiles=selflift_highres_tiles, upscaler_unload=True).out(0)
    else:
        noise = graph.node("RandomNoise", id="noise", noise_seed=seed)
        guider = graph.node("BasicGuider", id="guider", model=main_model, conditioning=conditioning)
        sampler = graph.node("KSamplerSelect", id="sampler", sampler_name=sampler_name)
        main = graph.node("SamplerCustomAdvanced", id="main", noise=noise.out(0), guider=guider.out(0),
                          sampler=sampler.out(0), sigmas=schedule, latent_image=reference.out(1))
        final = main.out(0)

    if two_pass and sampling_plan != "selflift":
        if isinstance(second_sigma_values, str):
            if second_sigma_values.strip():
                high_schedule = graph.node("ManualSigmas", id="high_sigmas", sigmas=second_sigma_values).out(0)
            else:
                high_schedule = graph.node("KarrasScheduler", id="high_sigmas", steps=second_steps,
                                           sigma_max=second_sigma_start, sigma_min=0.01, rho=second_rho).out(0)
        else:
            high_schedule = second_sigma_values
        high_noise = graph.node("RandomNoise", id="high_noise", noise_seed=seed)
        if sampling_plan == "tr":
            # Combined adds noise once, using exactly the second-pass schedule.
            upscaled = graph.node("MiniMaxH3LatentUpscaleCombined", id="upscale", samples=main.out(1),
                                  method=film_method, learned_model=film_model, model=high_model,
                                  noise=high_noise.out(0), sigmas=high_schedule, audio_denoise=film_audio_denoise,
                                  noise_resample=film_noise_resample, match_stats=film_match_stats,
                                  positive=conditioning)
            high_conditioning, latent = upscaled.out(1), upscaled.out(0)
            sampling_noise = graph.node("DisableNoise", id="film_disable_noise").out(0)
        else:
            split = graph.node("LTXVSeparateAVLatent", id="split_main", av_latent=main.out(1))
            upscaled = graph.node("easy minimaxH3LatentUpscaler", id="upscale", latent=split.out(0),
                                  model_name=upscale_model, mode="target dimensions",
                                  **{"mode.width": width, "mode.height": height}, align=32,
                                  enable_temporal_chunking=True, force_unload=True)
            latent = graph.node("LTXVConcatAVLatent", id="high_av",
                                video_latent=upscaled.out(0), audio_latent=split.out(1)).out(0)
            sampling_noise = high_noise.out(0)
        high_model = graph.node("YtonH3PrepareSampling", id="high_prepare_sampling",
                                model=high_model, clip=clip, conditioning=high_conditioning).out(0)
        high_guider = graph.node("BasicGuider", id="high_guider", model=high_model, conditioning=high_conditioning)
        high_sampler = graph.node("KSamplerSelect", id="high_sampler", sampler_name=second_sampler)
        final = graph.node("SamplerCustomAdvanced", id="high_sample", noise=sampling_noise,
                           guider=high_guider.out(0), sampler=high_sampler.out(0), sigmas=high_schedule,
                           latent_image=latent).out(0)

    frames = graph.node("VAEDecode", id="frames", samples=final, vae=vae).out(0)
    sound = graph.node("VAEDecodeAudio", id="sound", samples=final, vae=audio_vae).out(0)
    if face_refine:
        if isinstance(face_sigmas, str):
            face_sigmas = graph.node("ManualSigmas", id="face_sigmas", sigmas=face_sigmas).out(0) if face_sigmas.strip() else None
        face_model = model if face_model is None else face_model
        frames = add_face_refinement(graph, frames, final, face_model, clip, vae, audio_vae,
                                     image, prompt, ref_image_size, face_count, 4, 0.4,
                                     "bbox\\face_yolov8m.pt", face_reverse, 42, face_sigmas, 0.35, "none")

    trimmed = graph.node("YtonH3SegmentTrim", id="trim", images=frames, audio=sound,
                         head_trim_frames=0 if keep_context else head_trim_frames,
                         tail_trim_frames=tail_trim_frames, fps=24.0)
    frames = trimmed.out(0)
    if previous is not None:
        frames = _color_match(graph, frames, previous, "seamless_", context_color_strength,
                              CONTEXT_FRAMES if keep_context else 0)
    video_result = graph.node("CreateVideo", id="video", images=frames, audio=trimmed.out(1), fps=24.0)
    return {"result": (video_result.out(0), final), "expand": graph.finalize()}
