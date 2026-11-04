"""Save loop iterations to disk and concatenate only a complete ordered set."""

from pathlib import Path
from datetime import datetime
import json
import logging
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


def cleanup_files(*paths):
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            logging.warning("[yton-nodes] 文件暂时无法清理：%s (%s)", path, error)


def project_path(prefix, started_at):
    prefix = prefix.replace("%date:yyyy-MM-dd%", "%year%-%month%-%day%")
    directory = prefix.endswith(("/", "\\"))
    started_time = started_at.strftime("%H-%M-%S")
    folder, filename, _, _, _ = folder_paths.get_save_image_path(
        prefix + started_time if directory else prefix, folder_paths.get_output_directory())
    root = Path(folder) / (filename if directory else f"{filename}_{started_time}")
    pattern = re.compile(("" if directory else re.escape(filename) + "_") + r"\d{2}-\d{2}-\d{2}(?:-\d+)?$")
    return root, pattern


def read_manifest(root):
    path = root / "segments.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("segments"), dict):
            raise ValueError("片段清单结构无效")
        return manifest
    except FileNotFoundError:
        return None
    except ValueError as error:
        logging.warning("[yton-nodes] 片段清单无法读取，将按现有片段重建：%s (%s)", path, error)
        return None


def existing_project(prefix, started_at):
    root, pattern = project_path(prefix, started_at)
    candidates = []
    for candidate in root.parent.iterdir() if root.parent.is_dir() else ():
        manifest_path = candidate / "segments.json"
        if not candidate.is_dir() or not pattern.fullmatch(candidate.name):
            continue
        if not manifest_path.is_file() and not any(candidate.glob("segment_*")):
            continue
        manifest = read_manifest(candidate)
        candidates.append(((manifest_path if manifest_path.is_file() else candidate).stat().st_mtime_ns,
                           candidate, manifest))
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
            manifest = read_manifest(root)
        elif reuse_existing:
            existing = existing_project(prefix, started_at)
            if existing is not None:
                root, manifest = existing
        suffix = 1
        while project_root is None and not reuse_existing and manifest is None and root.exists():
            candidate = read_manifest(root)
            if candidate is not None and candidate.get("run") == run:
                manifest = candidate
                break
            suffix += 1
            root = base.with_name(f"{base.name}-{suffix}")
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "segments.json"
        if manifest is None:
            manifest = {"total": total, "segments": {}}
            for clip in sorted(root.glob("segment_*"), key=lambda path: path.stat().st_mtime_ns):
                match = re.fullmatch(r"segment_(\d+)\.(?:mp4|mkv)", clip.name)
                if match and clip.is_file():
                    try:
                        with av.open(str(clip)) as opened:
                            stream = opened.streams.video[0]
                            count = stream.frames or sum(1 for _ in opened.decode(stream))
                        manifest["segments"][str(int(match[1]))] = {"file": clip.name, "frames": count}
                    except (av.FFmpegError, IndexError) as error:
                        logging.warning("[yton-nodes] 跳过无法读取的旧片段：%s (%s)", clip, error)
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
            with av.open(str(staging)) as opened:
                stream = opened.streams.video[0]
                merge_timescale = stream.time_base.denominator if container == "mp4" else fps * 1024
                frame_count = stream.frames or sum(1 for _ in opened.decode(stream))
            staging.replace(target)
        finally:
            cleanup_files(source, staging)
        manifest.update(run=run, total=total, started_at=started_at.isoformat(), size=[width, height],
                        format=container, fps=fps, crf=crf)
        manifest["segments"][str(index)] = {"file": target.name, "frames": frame_count}
        pending = manifest_path.with_suffix(".writing.json")
        pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        pending.replace(manifest_path)
        cleanup_files(root / "complete.mp4", temp / "complete.mp4")
        for extension in ("mp4", "mkv"):
            obsolete = target.with_suffix("." + extension)
            if obsolete != target:
                cleanup_files(obsolete)
        records = [manifest["segments"][str(i)] for i in range(1, total + 1)
                   if str(i) in manifest["segments"] and (root / manifest["segments"][str(i)]["file"]).is_file()]
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
            except (ValueError, OSError, av.FFmpegError, IndexError) as error:
                logging.warning("[yton-nodes] 第 %s 段已保存到 %s；完整视频合并失败：%s", index, target, error)
                cleanup_files(merged)
                merged = None
            finally:
                cleanup_files(merging, concat, *normalized)
        return {"saved_segment": preview(target, "output"), "segments": [preview(path, "output") for path in clips],
                "merged": preview(merged, "output" if save_full else "temp") if merged else None,
                "complete": complete, "total": total, "current": index, "run": run, "_project_root": str(root)}
