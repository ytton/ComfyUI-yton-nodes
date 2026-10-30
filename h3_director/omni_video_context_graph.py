"""H3 generation with a previous VIDEO as the continuation guide."""

import math

from comfy_execution.graph_utils import GraphBuilder

from .omni_face import add_face_refinement
from .omni_sampling import FILM, FILM_MODEL, SELFLIFT, TRADITIONAL, sampling_dimensions

CONTEXT_FRAMES = 22


def _guide_from_previous(graph, previous, prefix):
    """前 21 帧加 0.1 噪声，最后一帧保持原样。"""
    first = graph.node("GetImageRangeFromBatch", id=prefix + "context_first",
                       images=previous.out(0), start_index=0, num_frames=CONTEXT_FRAMES - 1).out(0)
    last = graph.node("GetImageRangeFromBatch", id=prefix + "context_last",
                      images=previous.out(0), start_index=CONTEXT_FRAMES - 1, num_frames=1).out(0)
    first_noisy = graph.node("ImageAddNoise", id=prefix + "context_first_noise",
                             image=first, seed=0, strength=0.1).out(0)
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


def _color_match(graph, frames, previous, prefix):
    """用上一段最后一帧匹配本段颜色，整段共用首帧的变换。"""
    reference = graph.node("GetImageRangeFromBatch", id=prefix + "reference_frame",
                           images=previous.out(0), start_index=CONTEXT_FRAMES - 1,
                           num_frames=1).out(0)
    return graph.node("ColorTransfer", id=prefix + "color_match", image_target=frames,
                      image_ref=reference, method="mkl_lab",
                      source_stats="target_frame", **{"source_stats.target_index": 0},
                      strength=0.75).out(0)


def build_video_context_graph(model_loader, prompt, width, height, mode, duration, ref_image_size,
                              sampling_mode, steps, sampler_name, scheduler, denoise, seed,
                              first_pass_scale, upscale_model, second_sampler, second_sigma_values,
                              clip_index, face_refine, face_count, face_steps,
                              face_denoise, face_detector, face_reverse, face_large_strength,
                              face_fallback_detector, face_seed, image=None, video=None, audio=None,
                              sigmas=None, second_sigmas=None, previous_video=None, second_model=None,
                              face_model=None, face_sigmas=None, enable_context=False,
                              sampling_plan=TRADITIONAL, film_model=FILM_MODEL,
                              selflift_transition_step=2, selflift_rho=0.0, selflift_highres_tiling=False):
    width, height, main_width, main_height = sampling_dimensions(
        width, height, sampling_mode, sampling_plan, first_pass_scale)
    if not enable_context:
        previous_video = None
    graph = GraphBuilder()
    models = graph.node("fast modelFromLoader", id="models", **{"模型加载器": model_loader})
    two_pass = sampling_mode == "二采"
    selflift = two_pass and sampling_plan == SELFLIFT
    if selflift and sigmas is None and not 1 <= selflift_transition_step < steps:
        raise ValueError("SelfLift 低分步数必须小于主采样总步数；例如总计 4 步时，低分设为 2 步。")
    overlap = CONTEXT_FRAMES if previous_video is not None else 0

    source_images = source_audio = source_video = None
    if mode == "复刻模式":
        if video is None:
            raise ValueError("复刻模式需要传入至少一个视频，时长取第一个视频。")
        plan = graph.node("YtonH3ReplicaPlan", id="replica", video=video, context_frames=overlap)
        length = plan.out(0)
        head_trim_frames, tail_trim_frames = plan.out(1), plan.out(2)
    elif mode == "普通模式":
        if video is not None:
            plan = graph.node("YtonH3SegmentPlan", id="segment", duration=duration,
                              clip_index=clip_index, context_frames=overlap)
            length = plan.out(0)
            head_trim_frames, tail_trim_frames = plan.out(1), plan.out(2)
            source_start = plan.out(3)
        else:
            visible_frames = max(1, math.floor(float(duration) * 24 + 0.5))
            length = 5 + 17 * max(0, math.ceil((visible_frames + overlap - 5) / 17))
            length = max(39 if overlap else 5, length)
            head_trim_frames, tail_trim_frames = overlap, length - visible_frames - overlap
            source_start = None
    else:
        raise ValueError("请选择普通模式或复刻模式。")

    previous = None
    if previous_video is not None:
        previous = graph.node("YtonH3VideoTail", id="previous", video=previous_video)

    if video is not None and mode == "普通模式":
        components = graph.node("GetVideoComponents", id="source_components", video=video)
        source_images = graph.node("GetImageRangeFromBatch", id="source_images",
                                   images=components.out(0), start_index=source_start,
                                   num_frames=length).out(0)
        start_seconds = graph.node("ComfyMathExpression", id="source_start_seconds",
                                   expression="a / 24", **{"values.a": source_start}).out(0)
        source_duration = graph.node("ComfyMathExpression", id="source_duration",
                                     expression="a / 24", **{"values.a": length}).out(0)
        source_audio = graph.node("TrimAudioDuration", id="source_audio", audio=components.out(1),
                                  start_index=start_seconds, duration=source_duration).out(0)
        source_video = graph.node("CreateVideo", id="source_video", images=source_images,
                                  audio=source_audio, fps=components.out(2)).out(0)

    reference = graph.node("YtonMiniMaxH3ReferenceToVideo", id="reference",
                           clip=models.out(1), vae=models.out(2), audio_vae=models.out(3),
                           prompt=prompt, width=width if selflift else main_width,
                           height=height if selflift else main_height,
                           length=length, ref_image_size=ref_image_size)
    for name, link in (("image", image), ("video", source_video if source_video is not None else video),
                       ("audio", audio if source_video is None else None)):
        if link is not None:
            reference.set_input(name, link)

    conditioning = reference.out(0)
    if previous is not None:
        guide_images = _guide_from_previous(graph, previous, "main_ctx_")
        conditioning = _add_guide(graph, conditioning, reference.out(1), models.out(2), models.out(3),
                                   guide_images, previous.out(1), "main_context_add_guide")
    # 续段的头部由上一段引导；当前源视频继续作为 reference 使用。
    if source_images is not None and previous is None:
        conditioning = graph.node("MiniMaxH3AddGuide", id="source_guide", positive=conditioning,
                                   latent=reference.out(1), vae=models.out(2), image=source_images,
                                   frame_idx=0).out(0)

    schedule = sigmas
    if schedule is None:
        schedule = graph.node("BasicScheduler", id="schedule", model=models.out(0),
                              scheduler=scheduler, steps=steps, denoise=denoise).out(0)
    if selflift:
        # SelfLift owns both stages and consumes a target-resolution template.
        # CFG=1 preserves the generator's BasicGuider behavior; no uncond pass.
        sampler = graph.node("KSamplerSelect", id="sampler", sampler_name="euler")
        negative = graph.node("ConditioningZeroOut", id="selflift_negative", conditioning=conditioning)
        main = graph.node("SelfLiftH3Sampler", id="main", model=models.out(0), positive=conditioning,
                          negative=negative.out(0), vae=models.out(2), latent_image=reference.out(1),
                          sampler=sampler.out(0), sigmas=schedule, seed=seed, cfg=1.0,
                          transition_step=selflift_transition_step, lowres_scale=first_pass_scale,
                          rho=selflift_rho, w_min=0.5, w_max=1.0, upscaler_model=upscale_model,
                          highres_tiles="auto", highres_tiling=selflift_highres_tiling,
                          upscaler_unload=True, model_hires=models.out(0) if second_model is None else second_model)
    else:
        noise = graph.node("RandomNoise", id="noise", noise_seed=seed)
        guider = graph.node("BasicGuider", id="guider", model=models.out(0), conditioning=conditioning)
        sampler = graph.node("KSamplerSelect", id="sampler", sampler_name=sampler_name)
        main = graph.node("SamplerCustomAdvanced", id="main", noise=noise.out(0), guider=guider.out(0),
                          sampler=sampler.out(0), sigmas=schedule, latent_image=reference.out(1))
    final = main.out(0)

    if two_pass and not selflift:
        second_model = models.out(0) if second_model is None else second_model
        high_reference = graph.node("YtonMiniMaxH3ReferenceToVideo", id="high_reference",
                                    clip=models.out(1), vae=models.out(2), audio_vae=models.out(3),
                                    prompt="Enhance this video with sharp, crisp details while preserving a natural photorealistic appearance.",
                                    width=width, height=height, length=length, ref_image_size=ref_image_size)
        if image is not None:
            high_reference.set_input("image", image)
        if source_video is not None:
            high_reference.set_input("video", source_video)
        high_conditioning = high_reference.out(0)
        if previous is not None:
            high_guide_images = _guide_from_previous(graph, previous, "high_ctx_")
            high_conditioning = _add_guide(graph, high_conditioning, high_reference.out(1), models.out(2), models.out(3),
                                            high_guide_images, previous.out(1), "high_context_add_guide")
        if source_images is not None and previous is None:
            high_conditioning = graph.node("MiniMaxH3AddGuide", id="high_source_guide", positive=high_conditioning,
                                            latent=high_reference.out(1), vae=models.out(2), image=source_images,
                                            frame_idx=0).out(0)
        high_schedule = second_sigmas
        if high_schedule is None:
            high_schedule = graph.node("ManualSigmas", id="high_sigmas", sigmas=second_sigma_values).out(0)
        high_guider = graph.node("BasicGuider", id="high_guider", model=second_model,
                                 conditioning=high_conditioning)
        high_noise = graph.node("RandomNoise", id="high_noise", noise_seed=seed)
        if sampling_plan == FILM:
            # Combined adds CONST noise at exactly this schedule's first sigma.
            # Passing RandomNoise to the sampler again would add noise twice.
            upscaled = graph.node("MiniMaxH3LatentUpscaleCombined", id="upscale", samples=main.out(1),
                                  method="learned model", learned_model=film_model, model=second_model,
                                  noise=high_noise.out(0), sigmas=high_schedule, audio_denoise=0.0,
                                  noise_resample="independent", match_stats=0.0)
            latent = upscaled.out(0)
            sampling_noise = graph.node("DisableNoise", id="film_disable_noise").out(0)
        else:
            split = graph.node("LTXVSeparateAVLatent", id="split_main", av_latent=main.out(0))
            upscaled = graph.node("easy minimaxH3LatentUpscaler", id="upscale", latent=split.out(0),
                                  model_name=upscale_model, mode="target dimensions",
                                  **{"mode.width": width, "mode.height": height}, align=32,
                                  enable_temporal_chunking=True, force_unload=True)
            latent = graph.node("LTXVConcatAVLatent", id="high_av", video_latent=upscaled.out(0),
                                audio_latent=split.out(1)).out(0)
            sampling_noise = high_noise.out(0)
        high_sampler = graph.node("KSamplerSelect", id="high_sampler", sampler_name=second_sampler)
        final = graph.node("SamplerCustomAdvanced", id="high_sample", noise=sampling_noise,
                           guider=high_guider.out(0), sampler=high_sampler.out(0), sigmas=high_schedule,
                           latent_image=latent).out(0)

    frames = graph.node("VAEDecode", id="frames", samples=final, vae=models.out(2)).out(0)
    sound = graph.node("VAEDecodeAudio", id="sound", samples=final, vae=models.out(3)).out(0)
    if face_refine:
        face_model = models.out(0) if face_model is None else face_model
        frames = add_face_refinement(graph, frames, final, face_model, models.out(1), models.out(2), models.out(3),
                                     image, prompt, ref_image_size, face_count, face_steps, face_denoise,
                                     face_detector, face_reverse, face_seed, face_sigmas,
                                     face_large_strength, face_fallback_detector)

    trimmed = graph.node("YtonH3SegmentTrim", id="trim", images=frames, audio=sound,
                         head_trim_frames=head_trim_frames, tail_trim_frames=tail_trim_frames, fps=24.0)
    frames = trimmed.out(0)
    if previous is not None:
        frames = _color_match(graph, frames, previous, "seamless_")
    video_result = graph.node("CreateVideo", id="video", images=frames, audio=trimmed.out(1), fps=24.0)
    return {"result": (video_result.out(0), final), "expand": graph.finalize()}
