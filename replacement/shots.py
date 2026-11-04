"""Local camera-cut detection for the replacement editor, using PySceneDetect."""

from functools import lru_cache
import math

from .media import input_path, inspect
from .plan import FPS, make_plan


@lru_cache(maxsize=8)
def _cut_frames(path, modified, size, detector, sensitivity):
    # Optional import keeps ordinary editing usable without the detector installed.
    try:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import AdaptiveDetector, ContentDetector
    except ImportError:
        raise ValueError("按镜头切分需要 PySceneDetect，请安装节点包依赖后重启 ComfyUI。") from None

    video = open_video(str(path))
    manager = SceneManager()
    manager.auto_downscale = False
    manager.downscale = max(1, math.ceil(video.frame_size[0] / 320))
    minimum = max(3, round(video.frame_rate * .25))
    if detector == "content":
        detection = ContentDetector(threshold=45 - 33 * sensitivity, min_scene_len=minimum)
    else:
        detection = AdaptiveDetector(adaptive_threshold=5 - 3.5 * sensitivity, min_scene_len=minimum)
    manager.add_detector(detection)
    manager.detect_scenes(video=video, show_progress=False)
    return tuple(sorted({round(start.seconds * FPS)
                         for start, _ in manager.get_scene_list()[1:]}))


def shot_plan(filename, settings):
    detector = settings.get("detector", "adaptive")
    sensitivity = float(settings.get("sensitivity", .5))
    if detector not in ("adaptive", "content") or not math.isfinite(sensitivity) or not 0 <= sensitivity <= 1:
        raise ValueError("镜头检测方式或灵敏度无效。")
    path = input_path(filename)
    stat = path.stat()
    cuts = _cut_frames(path, stat.st_mtime_ns, stat.st_size, detector, sensitivity)
    settings = {**settings, "split": "shots", "cuts": list(cuts), "shot_source": filename}
    return {"settings": settings, "plan": make_plan(settings, inspect(filename)["duration"])}
