"""The LoadRef PGS segment rules, evaluated in frame space at 24 fps."""

import math


H3_FRAMES = tuple(range(22, 533, 17))
H3_CONTEXT = (0, 5, 22, 39, 56)
FPS = 24


def frame_round(value):
    return math.floor(float(value) * FPS + 0.5)


def make_plan(settings, duration):
    start = max(0, frame_round(settings.get("start", 0)))
    end = min(frame_round(duration), frame_round(settings.get("end") or duration))
    if start >= end:
        raise ValueError("视频选择范围需要满足开始时间小于结束时间。")
    enabled = settings.get("enabled", False)
    mode = settings.get("mode", "普通")
    output = settings.get("output", "完整片段")
    if mode not in ("普通", "MiniMax H3") or output not in ("完整片段", "仅新增片段"):
        raise ValueError("分段模式或输出方式无效。")
    if enabled and mode == "MiniMax H3":
        target = int(settings.get("frames", 175))
        if target not in H3_FRAMES:
            raise ValueError("H3 每段总帧数必须从合法帧数列表选择。")
    else:
        seconds = float(settings.get("seconds", 5))
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("每段时长需要大于 0 秒。")
        target = max(1, frame_round(seconds))
    context = int(settings.get("overlap", 0)) if enabled and output == "完整片段" else 0
    if context < 0 or (enabled and mode == "MiniMax H3" and context not in H3_CONTEXT):
        raise ValueError("上下文重叠帧数无效。")
    raw = min(target, end - start)
    if raw <= context:
        raise ValueError("每段总帧数需要大于上下文重叠帧数。")
    step = raw - context
    segments = [{"start": cursor, "end": min(cursor + raw, end)}
                for cursor in range(start, end, step) if min(cursor + raw, end) - cursor > context]
    return {"fps": FPS, "raw_frames": raw, "context_frames": context, "step": step,
            "mode": mode, "output": output, "segments": segments}
