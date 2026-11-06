"""The LoadRef PGS segment rules, evaluated in frame space at 24 fps."""

import math


H3_FRAMES = tuple(range(22, 533, 17))
H3_CONTEXT = (0, 5, 22, 39, 56)
FPS = 24


def frame_round(value):
    return math.floor(float(value) * FPS + 0.5)


def shot_segments(start, end, cuts, maximum, minimum, context):
    """Keep camera cuts, merge short shots when they fit, divide long shots evenly."""
    cuts = sorted({int(cut) for cut in cuts if start < int(cut) < end})
    edges = [start, *cuts, end]
    while len(edges) > 2:
        removal = None
        for position, (left, right) in enumerate(zip(edges, edges[1:])):
            if right - left >= minimum:
                continue
            candidates = []
            if position and right - edges[position - 1] <= maximum:
                candidates.append((right - edges[position - 1], position))
            if position + 2 < len(edges) and edges[position + 2] - left <= maximum:
                candidates.append((edges[position + 2] - left, position + 1))
            if candidates:
                removal = min(candidates)[1]
                break
        if removal is None:
            break
        edges.pop(removal)

    segments = []
    for left, right in zip(edges, edges[1:]):
        count = max(1, math.ceil((right - left - context) / (maximum - context)))
        boundaries = [left] + [left + context + math.floor((right - left - context) * i / count + .5)
                               for i in range(1, count + 1)]
        for index in range(count):
            segments.append({"start": boundaries[index] - (context if index else 0),
                             "end": boundaries[index + 1], "cut_before": index == 0 and left in cuts,
                             "context_frames": context if index else 0})
    return segments


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
    split = settings.get("split", "fixed")
    if enabled and settings.get("manual_segments") is not None:
        segments = []
        for item in settings["manual_segments"]:
            left, right = item["start"], item["end"]
            if type(left) is not int or type(right) is not int or not start <= left < right <= end:
                raise ValueError("手动分段边界须为选择范围内的有效帧数。")
            overlap = segments[-1]["end"] - left if segments else 0
            if segments and (overlap not in (0, context) or right <= segments[-1]["end"] or left <= segments[-1]["start"]):
                raise ValueError("手动分段须连续覆盖视频，并保持设置的上下文长度。")
            segments.append({"start": left, "end": right, "cut_before": bool(item.get("cut_before")),
                             "context_frames": overlap})
        if not segments or segments[0]["start"] != start or segments[-1]["end"] != end:
            raise ValueError("手动分段须完整覆盖选择的视频范围。")
    elif enabled and split == "shots":
        if "cuts" not in settings:
            raise ValueError("请先在视频编辑器中完成镜头检测并保存分段计划。")
        minimum = float(settings.get("min_seconds", 1))
        if not math.isfinite(minimum) or minimum < 0:
            raise ValueError("最短镜头时长需要大于或等于 0 秒。")
        segments = shot_segments(start, end, settings["cuts"], raw, min(raw, max(1, frame_round(minimum))), context)
    elif split == "fixed" or not enabled:
        segments = [{"start": cursor, "end": min(cursor + raw, end)}
                    for cursor in range(start, end, step) if min(cursor + raw, end) - cursor > context]
    else:
        raise ValueError("分段方式无效。")
    return {"fps": FPS, "raw_frames": raw, "context_frames": context, "step": step,
            "mode": mode, "output": output, "segments": segments}
