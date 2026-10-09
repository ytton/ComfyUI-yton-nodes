"""Fixed media slots and typed list/item parsers for ComfyUI."""

import os

import folder_paths
import numpy as np
import torch
from PIL import Image, ImageOps
from comfy_execution.graph_utils import ExecutionBlocker


MEDIA_SLOTS = {"image": 9, "video": 3, "audio": 3}


def resolve_media_file(filename):
    path = folder_paths.get_annotated_filepath(filename)
    if not os.path.isfile(path):
        raise ValueError(f"素材文件不存在：{filename}")
    return path


def media_fingerprint(**slots):
    files = []
    for kind, count in MEDIA_SLOTS.items():
        for index in range(1, count + 1):
            name = slots.get(f"{kind}_{index}", "").strip()
            if name:
                path = resolve_media_file(name)
                stat = os.stat(path)
                files.append((kind, index, path, stat.st_mtime_ns, stat.st_size))
    return tuple(files)


class YtonEasyMediaLoader:
    """Filenames are widget values; the node has no incoming sockets."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            f"{kind}_{index}": ("STRING", {"default": "", "multiline": False})
            for kind, count in MEDIA_SLOTS.items()
            for index in range(1, count + 1)
        }}

    RETURN_TYPES = ("MEDIA_BUNDLE", "YTON_IMAGE_LIST", "YTON_VIDEO_LIST", "YTON_AUDIO_LIST")
    RETURN_NAMES = ("media", "image_list", "video_list", "audio_list")
    FUNCTION = "load_media"
    CATEGORY = "yton-nodes/Media"
    DESCRIPTION = "固定 9 张图片、3 个视频、3 个音频。点击或拖入素材，列表中的位置对应面板槽位。"

    @classmethod
    def IS_CHANGED(cls, **slots):
        return media_fingerprint(**slots)

    @classmethod
    def VALIDATE_INPUTS(cls, **slots):
        try:
            media_fingerprint(**slots)
        except ValueError as error:
            return str(error)
        return True

    def load_media(self, **slots):
        lists = {}
        for kind, count in MEDIA_SLOTS.items():
            items = []
            for index in range(1, count + 1):
                filename = slots.get(f"{kind}_{index}", "").strip()
                items.append({"kind": kind, "filename": filename,
                              "path": resolve_media_file(filename), "slot": index} if filename else None)
            lists[kind] = items
        media = {"images": lists["image"], "videos": lists["video"], "audios": lists["audio"]}
        return media, lists["image"], lists["video"], lists["audio"]


class _MediaListParser:
    FUNCTION = "parse_list"
    CATEGORY = "yton-nodes/Media/解析"
    KIND = ""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {f"{cls.KIND}_list": (f"YTON_{cls.KIND.upper()}_LIST", {"forceInput": True})}}

    def parse_list(self, **inputs):
        items = inputs[f"{self.KIND}_list"]
        count = MEDIA_SLOTS[self.KIND]
        if not isinstance(items, (list, tuple)) or len(items) != count:
            raise ValueError(f"{self.KIND} 列表应包含 {count} 个固定槽位")
        return tuple(item if item is not None else ExecutionBlocker(None) for item in items)


class YtonImageListParser(_MediaListParser):
    KIND = "image"
    RETURN_TYPES = ("YTON_IMAGE",) * 9
    RETURN_NAMES = tuple(f"image_{index}" for index in range(1, 10))


class YtonVideoListParser(_MediaListParser):
    KIND = "video"
    RETURN_TYPES = ("YTON_VIDEO",) * 3
    RETURN_NAMES = ("video_1", "video_2", "video_3")


class YtonAudioListParser(_MediaListParser):
    KIND = "audio"
    RETURN_TYPES = ("YTON_AUDIO",) * 3
    RETURN_NAMES = ("audio_1", "audio_2", "audio_3")


def checked_media_path(media, kind):
    if not isinstance(media, dict) or media.get("kind") != kind:
        raise ValueError(f"需要 {kind} 素材")
    return resolve_media_file(media["filename"])


class YtonImageParser:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("YTON_IMAGE", {"forceInput": True})}}

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    FUNCTION = "parse_image"
    CATEGORY = "yton-nodes/Media/解析"

    def parse_image(self, image):
        with Image.open(checked_media_path(image, "image")) as source:
            source = ImageOps.exif_transpose(source)
            rgb = np.array(source.convert("RGB"), dtype=np.float32) / 255.0
            if "A" in source.getbands():
                mask = 1.0 - np.array(source.getchannel("A"), dtype=np.float32) / 255.0
            else:
                mask = np.zeros(rgb.shape[:2], dtype=np.float32)
        return torch.from_numpy(rgb).unsqueeze(0), torch.from_numpy(mask).unsqueeze(0)


class YtonVideoParser:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video": ("YTON_VIDEO", {"forceInput": True})}}

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "parse_video"
    CATEGORY = "yton-nodes/Media/解析"

    def parse_video(self, video):
        from comfy_api.latest import InputImpl

        return (InputImpl.VideoFromFile(checked_media_path(video, "video")),)


class YtonAudioParser:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio": ("YTON_AUDIO", {"forceInput": True})}}

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "parse_audio"
    CATEGORY = "yton-nodes/Media/解析"

    def parse_audio(self, audio):
        from comfy_extras.nodes_audio import load

        waveform, sample_rate = load(checked_media_path(audio, "audio"))
        return ({"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate},)
