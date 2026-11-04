"""Save loop iterations to disk and concatenate only a complete ordered set."""

from pathlib import Path
from datetime import datetime
import json
import re
import threading
import uuid

import av
import folder_paths

from .media import encode


_save_lock = threading.Lock()


def execution_state(dynprompt, unique_id):
    """Small execution-owned state, shared by native loop expansions."""
    owner = dynprompt.get_display_node_id(unique_id)
    if not hasattr(dynprompt, "yton_replacement"):
        dynprompt.yton_replacement = {}
        dynprompt.yton_replacement_started_at = datetime.now().astimezone()
    return dynprompt.yton_replacement.setdefault(owner, {
        "run": uuid.uuid4().hex, "started_at": dynprompt.yton_replacement_started_at, "prompts": {}})


def preview(path, kind):
    root = Path(folder_paths.get_output_directory() if kind == "output" else folder_paths.get_temp_directory())
    relative = path.relative_to(root)
    return {"filename": relative.name, "subfolder": relative.parent.as_posix(), "type": kind,
            "format": "video/" + ("mp4" if path.suffix == ".mp4" else "x-matroska")}


def project_path(prefix, started_at):
    prefix = prefix.replace("%date:yyyy-MM-dd%", "%year%-%month%-%day%")
    directory = prefix.endswith(("/", "\\"))
    started_time = started_at.strftime("%H-%M-%S")
    folder, filename, _, _, _ = folder_paths.get_save_image_path(
        prefix + started_time if directory else prefix, folder_paths.get_output_directory())
    root = Path(folder) / (filename if directory else f"{filename}_{started_time}")
    pattern = re.compile(("" if directory else re.escape(filename) + "_") + r"\d{2}-\d{2}-\d{2}(?:-\d+)?$")
    return root, pattern


def existing_project(prefix, started_at, total):
    root, pattern = project_path(prefix, started_at)
    candidates = []
    for candidate in root.parent.iterdir() if root.parent.is_dir() else ():
        manifest_path = candidate / "segments.json"
        if not candidate.is_dir() or not manifest_path.is_file() or not pattern.fullmatch(candidate.name):
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("total") == total:
            candidates.append((manifest_path.stat().st_mtime_ns, candidate, manifest))
    if not candidates:
        return None
    _, root, manifest = max(candidates, key=lambda item: item[0])
    return root, manifest


def save_segment(video, index, total, *, run, started_at, prefix, container="mp4", fps=24, crf=18,
                 reuse_existing=False, save_full=True, project_root=None):
    if not (1 <= index <= total):
        raise ValueError("当前段从 1 开始，且不能超过视频总段数。")
    if container not in ("mp4", "mkv") or not re.fullmatch(r"[a-f0-9]{32}", run):
        raise ValueError("保存格式或运行标识无效。")
    if fps <= 0 or not 0 <= crf <= 51:
        raise ValueError("保存帧率或质量值无效。")
    # Resolve the user prefix through ComfyUI's output path containment check.
    root, _ = project_path(prefix, started_at)
    temp = Path(folder_paths.get_temp_directory()) / "yton-replacement" / run
    temp.mkdir(parents=True, exist_ok=True)
    with _save_lock:
        base = root
        manifest = None
        if project_root is not None:
            root = Path(project_root)
            manifest_path = root / "segments.json"
            if not manifest_path.is_file():
                raise ValueError("当前项目目录缺少片段清单，无法继续保存。")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        elif reuse_existing:
            existing = existing_project(prefix, started_at, total)
            if existing is not None:
                root, manifest = existing
        suffix = 1
        while manifest is None and root.exists():
            manifest_path = root / "segments.json"
            if manifest_path.is_file():
                candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
                if candidate["run"] == run:
                    manifest = candidate
                    break
            suffix += 1
            root = base.with_name(f"{base.name}-{suffix}")
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "segments.json"
        if manifest is None:
            manifest = {"total": total, "segments": {}}
        if manifest["total"] != total:
            raise ValueError("同一轮循环的总段数需要保持一致。")
        source = temp / "input.mp4"
        target = root / f"segment_{index:04d}.{container}"
        staging = root / f"segment_{index:04d}.writing.{container}"
        width, height = [side - side % 2 for side in video.get_dimensions()]
        try:
            video.save_to(str(source))
            with av.open(str(source)) as opened:
                has_audio = bool(opened.streams.audio)
                stream = opened.streams.video[0]
                duration = float(stream.duration * stream.time_base)
            audio_source = [] if has_audio else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            # FFmpeg 7.1 can drop the last frame when fps follows spatial filters.
            encode(["-i", source, *audio_source, "-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0",
                    "-vf", f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                    "-c:v", "libx264", "-preset", "fast", "-crf", crf, "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2",
                    "-af", f"apad,atrim=duration={duration:.12f},asetpts=PTS-STARTPTS", "-t", f"{duration:.12f}",
                    *(["-movflags", "+faststart"] if container == "mp4" else []), staging])
            staging.replace(target)
        finally:
            source.unlink(missing_ok=True)
            staging.unlink(missing_ok=True)
        with av.open(str(target)) as opened:
            stream = opened.streams.video[0]
            merge_timescale = stream.time_base.denominator if container == "mp4" else fps * 1024
            frame_count = stream.frames or sum(1 for _ in opened.decode(stream))
        previous = manifest["segments"].get(str(index))
        manifest.update(run=run, started_at=started_at.isoformat(), size=[width, height],
                        format=container, fps=fps, crf=crf)
        manifest["segments"][str(index)] = {"file": target.name, "frames": frame_count}
        pending = manifest_path.with_suffix(".writing.json")
        pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        pending.replace(manifest_path)
        if previous and previous["file"] != target.name:
            (root / previous["file"]).unlink(missing_ok=True)
        records = [manifest["segments"][str(i)] for i in range(1, total + 1) if str(i) in manifest["segments"]]
        clips = [root / record["file"] for record in records]
        complete = len(clips) == total
        merged = None
        if complete:
            concat = root / "concat.txt"
            merged = (root if save_full else temp) / "complete.mp4"
            merging = merged.with_suffix(".writing.mp4")
            normalized = []
            try:
                merge_records = []
                for i, record in enumerate(records, 1):
                    clip = root / record["file"]
                    with av.open(str(clip)) as opened:
                        stream = opened.streams.video[0]
                        rate = stream.average_rate
                        size = (stream.width, stream.height)
                        time_base = stream.time_base
                    # MKV timestamps use milliseconds; rebuild the exact frame grid for MP4.
                    transcode = size != (width, height) or rate != fps or clip.suffix != ".mp4"
                    if transcode or (time_base.numerator, time_base.denominator) != (1, merge_timescale):
                        # Normalize a merge copy; keep the saved segment at its own settings.
                        clip = root / f"merge_{i:04d}.mp4"
                        normalized.append(clip)
                        options = ["-c", "copy"]
                        if transcode:
                            duration = record["frames"] / float(rate)
                            options = ["-vf", f"setpts=PTS-STARTPTS,fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                                       "-c:v", "libx264", "-preset", "fast", "-crf", crf, "-pix_fmt", "yuv420p",
                                       "-c:a", "aac", "-ar", "48000", "-ac", "2",
                                       "-af", f"apad,atrim=duration={duration:.12f},asetpts=PTS-STARTPTS",
                                       "-t", f"{duration:.12f}"]
                        encode(["-i", root / record["file"], *options,
                                "-video_track_timescale", merge_timescale, "-movflags", "+faststart", clip])
                        with av.open(str(clip)) as opened:
                            stream = opened.streams.video[0]
                            count = stream.frames or sum(1 for _ in opened.decode(stream))
                        merge_records.append({"file": clip.name, "frames": count})
                    else:
                        merge_records.append(record)
                # Relative paths are generated by us, never interpreted as shell commands.
                concat.write_text("\n".join(f"file '{record['file']}'\nduration {record['frames'] / fps:.12f}"
                                             for record in merge_records), encoding="utf-8")
                encode(["-f", "concat", "-safe", "1", "-i", concat, "-c:v", "copy",
                        "-c:a", "aac", "-af", "aresample=async=1:first_pts=0",
                        "-t", sum(record["frames"] for record in merge_records) / fps,
                        "-movflags", "+faststart", merging])
                merging.replace(merged)
            finally:
                merging.unlink(missing_ok=True)
                concat.unlink(missing_ok=True)
                for clip in normalized:
                    clip.unlink(missing_ok=True)
        return {"saved_segment": preview(target, "output"), "segments": [preview(path, "output") for path in clips],
                "merged": preview(merged, "output" if save_full else "temp") if merged else None,
                "complete": complete, "total": total, "current": index, "run": run, "_project_root": str(root)}
