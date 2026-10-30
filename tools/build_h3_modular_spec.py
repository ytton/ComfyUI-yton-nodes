"""Create the editable node specification consumed by build_h3_modular.browser.js.

Run from the plugin root. This script only writes specifications; it never queues
a ComfyUI job or loads a model.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(variant):
    nodes, modules = [], {}

    def node(key, kind, module, title, **values):
        item = dict(key=key, type=kind, module=module, title=title, values=values)
        nodes.append(item)
        modules.setdefault(module, []).append(key)
        return key, 0

    def out(ref, slot):
        return ref[0], slot

    def choose(key, module, title, flag, yes, no, kind):
        ref = node(key, "easy ifElse", module, title, boolean=flag, on_true=yes, on_false=no)
        nodes[-1]["outputType"] = kind
        return ref

    def math(key, module, title, expression, *args, slot=1):
        return out(node(key, "ComfyMathExpression", module, title, expression=expression,
                        **{f"values.{chr(97+i)}": x for i, x in enumerate(args)}), slot)

    def primitive(key, kind, title, value):
        return node(key, kind, "params", title, value=value)

    requested_width = primitive("width", "PrimitiveInt", "目标宽度（自动按 64 对齐）", 1344)
    requested_height = primitive("height", "PrimitiveInt", "目标高度（自动按 64 对齐）", 768)
    width = math("target_width", "params", "实际目标宽度 / 64 对齐", "max(64, round(a / 64) * 64)", requested_width)
    height = math("target_height", "params", "实际目标高度 / 64 对齐", "max(64, round(a / 64) * 64)", requested_height)
    duration = primitive("duration", "PrimitiveFloat", "成片时长 / 秒（普通模式）", 5.0)
    seed = primitive("seed", "PrimitiveInt", "随机种子（固定便于对照）", 42)
    two = primitive("two_pass", "PrimitiveBoolean", "启用二采与超分", True)
    context = primitive("enable_context", "PrimitiveBoolean", "启用上一段视频上下文", False)
    replica = primitive("replica_mode", "PrimitiveBoolean", "复刻模式：以第一个视频时长为准", False)
    face = primitive("enable_face", "PrimitiveBoolean", "启用小脸精修", False)
    color = primitive("enable_color", "PrimitiveBoolean", "启用接续色彩匹配", True)
    clip_index = primitive("clip_index", "PrimitiveInt", "源视频普通模式：第几段", 1)
    prompt = node("prompt", "PrimitiveStringMultiline", None, "生成提示词 · 引用编号按素材顺序",
                  value="A cinematic shot of a pelican riding a bicycle along a sunny coastal road. Natural daylight, stable camera, realistic feather details and smooth movement. Gentle sea breeze and bicycle sounds.")
    media = node("media", "YtonEasyMediaLoader", None, "当前素材 · 图片 / 视频 / 音频均可留空")
    previous_media = node("previous_media", "YtonEasyMediaLoader", None, "上一段成片 · 只填写第一个视频")

    original = json.loads((ROOT / "examples/H3_全模态生成_TR.json").read_text(encoding="utf-8"))
    loader_preset = next(n for n in original["nodes"] if n["type"] == "fast h3Loader")
    loader = node("loader", "fast h3Loader", "models", "H3 模型加载器")
    nodes[-1]["preset"] = loader_preset["widgets_values"]
    unpack = node("models", "fast modelFromLoader", "models", "拆出模型 / CLIP / 双 VAE", **{"#0": loader})
    clip, vae, audio_vae = out(unpack, 1), out(unpack, 2), out(unpack, 3)
    model = node("lowvram", "MiniMaxLowVRAMAttention", "models", "注意力显存分块", model=unpack, head_chunks=4)
    model = node("ff", "MiniMaxChunkFeedForward", "models", "前馈分块", model=model, chunks=2, seq_threshold=4096)
    model = node("attention", "ModelAttentionBackend", "models", "注意力后端", model=model, attention="comfy kitchen attention")
    base = node("shift", "MiniMaxH3SigmaShift", "models", "视频 / 音频 Sigma Shift", model=model, shift_video=12.0, shift_audio=3.0)
    sparse = node("sparse", "BlockSparseAttention", "models", "首采稀疏注意力", model=base, selection="sol-attn",
                  **{"selection.tau": 1.3}, start_percent=0.2, end_percent=1.0)
    swap = node("swap", "LoraLoaderModelOnly", "models", "人物替换 LoRA（默认关闭，按实验需要打开）", model=sparse,
                lora_name="H3\\minimax_h3_character_swap_v1.1_ref2va_fro.safetensors", strength_model=0.0)
    turbo_name = "H3\\minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy_resized_avg_rank_21_bf16.safetensors"
    main_model = node("main_model", "LoraLoaderModelOnly", "models", "首采 Turbo LoRA", model=swap, lora_name=turbo_name, strength_model=1.0)
    second_model = node("second_model", "LoraLoaderModelOnly", "models", "二采 / 精修 Turbo LoRA", model=base, lora_name=turbo_name, strength_model=1.0)

    first_video = node("first_video", "YtonVideoListParser", "plan", "取第一个源视频；空列表输出 None", video=out(media, 1))
    previous = node("first_previous", "YtonVideoListParser", "plan", "取上一段成片；空列表输出 None", video=out(previous_media, 1))
    no_previous = node("no_previous", "easy isNone", "plan", "上一段是否为空", any=previous)
    no_source = node("no_source", "easy isNone", "plan", "源视频是否为空", any=first_video)
    has_context = math("has_context", "plan", "仅开关打开且有上段才接续", "a and not b", context, no_previous, slot=2)
    overlap = math("overlap", "plan", "上下文固定 22 帧；关闭为 0", "22 if a else 0", has_context)
    normal = node("normal_plan", "YtonH3SegmentPlan", "plan", "普通模式：补上下文与 H3 帧格", duration=duration,
                  clip_index=clip_index, context_frames=overlap)
    copy = node("replica_plan", "YtonH3ReplicaPlan", "plan", "复刻模式：读取第一个视频时长", video=first_video, context_frames=overlap)
    length = choose("length", "plan", "选择采样总帧数", replica, copy, normal, "INT")
    head = choose("head", "plan", "选择头部裁切帧数", replica, out(copy, 1), out(normal, 1), "INT")
    tail = choose("tail", "plan", "选择尾部裁切帧数", replica, out(copy, 2), out(normal, 2), "INT")
    low_w = math("low_w", "plan", "首采宽度：二采时 1/2，否则目标宽度", "max(32, round(a / 64) * 32) if b else a", width, two)
    low_h = math("low_h", "plan", "首采高度：二采时 1/2，否则目标高度", "max(32, round(a / 64) * 32) if b else a", height, two)
    # Only the selected lazy branch may read a VIDEO. Empty uploads never reach GetVideoComponents.
    components = node("source_components", "GetVideoComponents", "source", "源视频拆帧（源视频请使用 24fps）", video=first_video)
    source_images = node("source_range", "GetImageRangeFromBatch", "source", "普通模式截取当前片段和上下文", images=components,
                         start_index=out(normal, 3), num_frames=length)
    start_seconds = math("start_seconds", "source", "源视频起点 / 秒", "a / 24", out(normal, 3), slot=0)
    source_seconds = math("source_seconds", "source", "源视频截取时长 / 秒", "a / 24", length, slot=0)
    audio_none = node("source_audio_none", "easy isNone", "source", "无声视频不裁音频", any=out(components, 1))
    source_audio = node("source_audio", "TrimAudioDuration", "source", "同步截取源视频声音", audio=out(components, 1),
                        start_index=start_seconds, duration=source_seconds)
    source_audio = choose("source_audio_safe", "source", "允许无声源视频", audio_none, out(components, 1), source_audio, "AUDIO")
    source_video = node("source_video", "CreateVideo", "source", "当前源视频片段", images=source_images, audio=source_audio, fps=out(components, 2))
    reference_video = choose("mode_video", "source", "复刻保留全部视频参考；普通模式用首个视频切片", replica, out(media, 1), source_video, "VIDEO")
    reference_video = choose("safe_video", "source", "没有源视频则传 None", no_source, first_video, reference_video, "VIDEO")

    previous_tail = node("previous_tail", "YtonH3VideoTail", "context", "读取上段尾部 22 帧及同步声音", video=previous)
    first21 = node("context_first21", "GetImageRangeFromBatch", "context", "上下文前 21 帧", images=previous_tail, start_index=0, num_frames=21)
    first21 = node("context_noise", "ImageAddNoise", "context", "前 21 帧加噪 0.1", image=first21, seed=0, strength=0.1)
    last = node("context_last", "GetImageRangeFromBatch", "context", "上下文最后一帧保持原样", images=previous_tail, start_index=21, num_frames=1)
    guide = node("context_batch", "ImageBatchMulti", "context", "合并为完整 22 帧上下文", inputcount=2, image_1=first21, image_2=last)
    source_guide_candidate = math("source_guide_candidate", "plan", "普通模式且有源视频", "not a and not b", replica, no_source, slot=2)
    use_source_guide = math("use_source_guide", "plan", "仅普通源视频且无上段时使用源画面引导", "a and not b", source_guide_candidate, has_context, slot=2)

    def reference(key, module, title, w, h, text, use_video=True, use_audio=True):
        args = dict(clip=clip, vae=vae, audio_vae=audio_vae, prompt=text, width=w, height=h,
                    length=length, ref_image_size="match", image=media)
        if use_video:
            args["video"] = reference_video
        if use_audio:
            args["audio"] = out(media, 2)
        ref = node(key, "YtonMiniMaxH3ReferenceToVideo", module, title, **args)
        source_cond = node(key+"_source", "MiniMaxH3AddGuide", module, "普通源视频画面引导", positive=ref,
                           latent=out(ref, 1), vae=vae, image=source_images, frame_idx=0)
        source_cond = choose(key+"_source_select", module, "无源视频时绕过画面引导", use_source_guide, source_cond, ref, "CONDITIONING")
        context_cond = node(key+"_context", "MiniMaxH3AddGuide", module, "加入上一段尾部画面与声音", positive=ref,
                            latent=out(ref, 1), vae=vae, audio_vae=audio_vae, image=guide, audio=out(previous_tail, 1), frame_idx=0)
        feather = node(key+"_feather", "MiniMaxH3AudioGuideFeather", module, "释放上下文尾部音频约束", positive=context_cond, audio_feather_ticks=256)
        cond = choose(key+"_select", module, "上下文开关（惰性执行）", has_context, feather, source_cond, "CONDITIONING")
        return cond, out(ref, 1)

    positive, latent = reference("reference", "reference", "首采参考编码 · 可选素材列表", low_w, low_h, prompt)
    schedule = node("main_schedule", "BasicScheduler", "main", "首采调度（可替换 ManualSigmas）", model=main_model, scheduler="simple", steps=4, denoise=1.0)
    noise = node("main_noise", "RandomNoise", "main", "首采噪声", noise_seed=seed)
    guider = node("main_guider", "BasicGuider", "main", "首采模型 + 条件", model=main_model, conditioning=positive)
    sampler = node("main_sampler", "KSamplerSelect", "main", "首采采样器", sampler_name="euler")
    sampled = node("main_sample", "SamplerCustomAdvanced", "main", "首采 · 输出与干净结果均可观察", noise=noise,
                   guider=guider, sampler=sampler, sigmas=schedule, latent_image=latent)
    clean = out(sampled, 1)

    high_positive, _ = reference("high_reference", "high", "按目标尺寸重新编码二采条件", width, height,
                                 "Enhance this video with sharp, crisp details while preserving a natural photorealistic appearance.", use_audio=False)
    high_schedule = node("high_schedule", "ManualSigmas", "high", "二采 Sigma（与加噪保持同一条线）",
                         sigmas="0.35, 0.175, 0" if variant == "film" else "0.631578922, 0.3158, 0")
    high_random = node("high_random", "RandomNoise", "high", "二采随机噪声源", noise_seed=seed)
    if variant == "film":
        high_latent = node("upscale_film", "MiniMaxH3LatentUpscaleCombined", "high", "Film 固定 2× · FP32 超分并重新加噪",
                           samples=clean, model=second_model, noise=high_random, sigmas=high_schedule, method="learned model",
                           learned_model="h3_clean_latent_upscaler_film_epoch200.safetensors", audio_denoise=0.0,
                           noise_resample="independent", match_stats=0.0)
        high_noise = node("high_noise", "DisableNoise", "high", "Film 已加噪：二采必须禁用再次加噪")
    else:
        separate = node("separate", "LTXVSeparateAVLatent", "high", "分离首采视频与音频", av_latent=clean)
        upscale = node("upscale_3d", "easy minimaxH3LatentUpscaler", "high", "3D / LMS 潜空间超分 · 可直接更换权重", latent=separate,
                       model_name="minimax_h3_latent_upscaler_3d_fp16.safetensors", mode="scale by multiplier",
                       **{"mode.scale": 2.0}, align=32, enable_temporal_chunking=True, force_unload=True)
        high_latent = node("high_av", "LTXVConcatAVLatent", "high", "合回首采原音频", video_latent=upscale, audio_latent=out(separate, 1))
        high_noise = high_random
    high_guider = node("high_guider", "BasicGuider", "high", "二采模型 + 高分辨率条件", model=second_model, conditioning=high_positive)
    high_sampler = node("high_sampler", "KSamplerSelect", "second", "二采采样器", sampler_name="sa_solver")
    high_sample = node("high_sample", "SamplerCustomAdvanced", "second", "二采 · 模块噪声输出必须成套连接", noise=high_noise,
                       guider=high_guider, sampler=high_sampler, sigmas=high_schedule, latent_image=high_latent)
    final = choose("final_latent", "second", "单采时整段超分与二采不执行", two, high_sample, sampled, "LATENT")

    frames = node("decode", "VAEDecode", "second", "解码视频画面 · 作为精修模块的底图", samples=final, vae=vae)
    sound = node("decode_audio", "VAEDecodeAudio", "output", "解码生成音频", samples=final, vae=audio_vae)
    crop = node("face_crop", "H3FaceTrackCrop", "face", "追踪第 1 人（复制精修模块可增加人数）", images=frames,
                detector="bbox\\face_yolov8m.pt", confidence=0.35, crop_factor=2.5, canvas_width=768, canvas_height=768,
                canvas_mode="auto_capped_768", smooth_window=21, size_smooth_window=51, smooth_method="gaussian", size_mode="per_frame",
                identity_track=True, identity_threshold=0.28, select="largest_face", select_index=0, identity_model="insightface",
                fallback_detector="segm\\person_yolov8m-seg.pt", fallback_head_frac=0.5, cut_detection="none", absent_shots="off")
    face_reference = node("face_reference", "YtonMiniMaxH3ReferenceToVideo", "face", "人脸局部参考编码", clip=clip, vae=vae, audio_vae=audio_vae,
                          image=media, prompt=prompt, width=out(crop, 4), height=out(crop, 5), length=out(crop, 6), ref_image_size="match")
    injected = node("face_inject", "H3InjectVideoLatent", "face", "编码并注入人脸局部画面", av_latent=out(face_reference, 1), images=crop, vae=vae)
    face_split = node("face_split", "LTXVSeparateAVLatent", "face", "拆分局部视频 latent", av_latent=injected)
    original_sound = node("face_original_audio", "LTXVSeparateAVLatent", "face", "保留成片音频 latent", av_latent=final)
    face_av = node("face_av", "LTXVConcatAVLatent", "face", "局部画面 + 原音频", video_latent=face_split, audio_latent=out(original_sound, 1))
    adaptive = node("face_denoise", "H3PerFrameDenoise", "face", "按人脸大小控制逐帧降噪", model=second_model, av_latent=face_av, transform=out(crop, 1),
                    denoise_multiplier_small_face=1.0, denoise_multiplier_large_face=0.35, scale_mode="absolute_px", face_px_small=30.0,
                    face_px_large=120.0, gamma=1.0, smooth_frames=9)
    face_schedule = node("face_schedule", "BasicScheduler", "face", "精修强度 0.4；换 Sigma 时直接替换此节点", model=out(adaptive, 2), scheduler="simple", steps=4, denoise=0.4)
    face_noise = node("face_noise", "RandomNoise", "face", "精修种子", noise_seed=seed)
    face_guider = node("face_guider", "BasicGuider", "face", "精修模型 + 条件", model=out(adaptive, 2), conditioning=face_reference)
    face_sampler = node("face_sampler", "KSamplerSelect", "face", "精修采样器", sampler_name="er_sde")
    face_sample = node("face_sample", "SamplerCustomAdvanced", "face", "人脸局部采样", noise=face_noise, guider=face_guider,
                       sampler=face_sampler, sigmas=face_schedule, latent_image=adaptive)
    face_decode = node("face_decode", "VAEDecode", "face", "解码精修局部", samples=face_sample, vae=vae)
    stitch = node("face_stitch", "H3FaceStitch", "face", "颜色匹配与羽化贴回", base_images=frames, refined_crops=face_decode,
                  transform=out(crop, 1), paste_region="face_only", mask_dilation=24, feather=24, colour_match=1.0, blend=1.0,
                  undetected_frames="fade_out", feather_scales_with_crop=False)
    frames = choose("face_select", "face", "关闭精修时不检测与采样人脸", face, stitch, frames, "IMAGE")
    trimmed = node("trim", "YtonH3SegmentTrim", "output", "去掉上下文及帧格增量，保留目标时长", images=frames, audio=sound,
                   head_trim_frames=head, tail_trim_frames=tail, fps=24.0)
    match_flag = math("match_flag", "output", "有上下文且开启调色时才匹配", "a and b", has_context, color, slot=2)
    matched = node("color_match", "ColorTransfer", "output", "整段共用首帧变换，匹配上段尾帧", image_target=trimmed, image_ref=last,
                   method="mkl_lab", source_stats="target_frame", **{"source_stats.target_index": 0}, strength=0.75)
    frames = choose("color_select", "output", "色彩模块可单独绕过做对照", match_flag, matched, trimmed, "IMAGE")
    video = node("video", "CreateVideo", "output", "合成当前片段（不附加上段）", images=frames, audio=out(trimmed, 1), fps=24.0)
    node("save", "SaveVideo", None, "预览并保存当前成片", video=video, filename_prefix=f"H3实验/{variant}/H3", format="auto")
    return dict(variant=variant, nodes=nodes, modules={k: v for k, v in modules.items() if k},
                names={"params":"00 参数与功能开关", "models":"01 模型与 LoRA", "plan":"02 时长与素材判断", "source":"02a 源视频切片",
                       "context":"02b 上段尾部 22 帧", "reference":"03 首采参考与引导", "main":"04 首次采样",
                       "high":f"05 超分与二采准备 · {'Film 2×' if variant == 'film' else '3D / LMS'}", "second":"06 第二次采样与单采开关",
                       "face":"07 小脸精修（可选）", "output":"08 裁切与色彩匹配"})


if __name__ == "__main__":
    target = ROOT / "temp/h3-modular-spec.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps([build("3d"), build("film")], ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)
