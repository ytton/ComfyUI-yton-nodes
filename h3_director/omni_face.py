"""Assemble the installed H3 FaceRefine nodes; no face-processing implementation."""


def add_face_refinement(graph, frames, av_latent, models, image, prompt, ref_image_size,
                        count, steps, denoise, detector, reverse, seed):
    if reverse:
        frames = graph.node("ReverseImageBatch", id="face_reverse", images=frames).out(0)
    original_audio = graph.node("LTXVSeparateAVLatent", id="face_audio", av_latent=av_latent).out(1)
    for index in range(count):
        prefix = f"face_{index}_"
        crop = graph.node("H3FaceTrackCrop", id=prefix + "crop", images=frames,
            detector=detector, confidence=0.35, crop_factor=2.5,
            canvas_width=768, canvas_height=768, canvas_mode="auto_capped_768",
            smooth_window=21, size_smooth_window=51, smooth_method="gaussian", size_mode="per_frame",
            identity_track=True, identity_threshold=0.28, select="largest_face", select_index=index,
            identity_model="insightface", fallback_detector="none", cut_detection="none", absent_shots="off")
        reference = graph.node("YtonMiniMaxH3ReferenceToVideo", id=prefix + "reference",
            clip=models.out(1), vae=models.out(2), audio_vae=models.out(3), prompt=prompt,
            width=crop.out(4), height=crop.out(5), length=crop.out(6), ref_image_size=ref_image_size)
        if image is not None:
            reference.set_input("image", image)
        injected = graph.node("H3InjectVideoLatent", id=prefix + "inject",
            av_latent=reference.out(1), images=crop.out(0), vae=models.out(2))
        split = graph.node("LTXVSeparateAVLatent", id=prefix + "split", av_latent=injected.out(0))
        av = graph.node("LTXVConcatAVLatent", id=prefix + "av",
            video_latent=split.out(0), audio_latent=original_audio)
        adaptive = graph.node("H3PerFrameDenoise", id=prefix + "denoise",
            model=models.out(0), av_latent=av.out(0), transform=crop.out(1),
            denoise_multiplier_small_face=1.0, denoise_multiplier_large_face=0.35,
            scale_mode="absolute_px", face_px_small=30.0, face_px_large=120.0, gamma=1.0, smooth_frames=9)
        guider = graph.node("BasicGuider", id=prefix + "guider",
            model=adaptive.out(2), conditioning=reference.out(0))
        schedule = graph.node("BasicScheduler", id=prefix + "schedule",
            model=adaptive.out(2), scheduler="simple", steps=steps, denoise=denoise)
        noise = graph.node("RandomNoise", id=prefix + "noise", noise_seed=(seed + 100 + index) % (1 << 64))
        sampler = graph.node("KSamplerSelect", id=prefix + "sampler", sampler_name="er_sde")
        sample = graph.node("SamplerCustomAdvanced", id=prefix + "sample",
            noise=noise.out(0), guider=guider.out(0), sampler=sampler.out(0),
            sigmas=schedule.out(0), latent_image=adaptive.out(0))
        decoded = graph.node("VAEDecode", id=prefix + "decode", samples=sample.out(0), vae=models.out(2))
        frames = graph.node("H3FaceStitch", id=prefix + "stitch", base_images=frames,
            refined_crops=decoded.out(0), transform=crop.out(1), paste_region="face_only",
            mask_dilation=24, feather=24, colour_match=1.0, blend=1.0,
            undetected_frames="fade_out", feather_scales_with_crop=False).out(0)
    if reverse:
        frames = graph.node("ReverseImageBatch", id="face_restore_order", images=frames).out(0)
    return frames
