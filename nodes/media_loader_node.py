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

    RETURN_TYPES = ("IMAGE", "VIDEO", "AUDIO")
    RETURN_NAMES = ("image", "video", "audio")
    OUTPUT_IS_LIST = (True, True, True)
    FUNCTION = "load_media"
    CATEGORY = "yton-nodes/Media"
    DESCRIPTION = "固定 9 张图片、3 个视频、3 个音频。按槽位顺序输出原生媒体列表，空槽位不加入列表。"

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
                if not filename:
                    continue
                path = resolve_media_file(filename)
                if kind == "image":
                    with Image.open(path) as source:
                        source = ImageOps.exif_transpose(source)
                        rgb = np.array(source.convert("RGB"), dtype=np.float32) / 255.0
                    items.append(torch.from_numpy(rgb).unsqueeze(0))
                elif kind == "video":
                    from comfy_api.latest import InputImpl

                    items.append(InputImpl.VideoFromFile(path))
                else:
                    from comfy_extras.nodes_audio import load

                    waveform, sample_rate = load(path)
                    items.append({"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate})
            lists[kind] = items
        return lists["image"], lists["video"], lists["audio"]


class _MediaListParser:
    FUNCTION = "parse_list"
    CATEGORY = "yton-nodes/Media/解析"
    KIND = ""
    INPUT_IS_LIST = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {f"{cls.KIND}_list": (cls.KIND.upper(), {"forceInput": True})}}

    def parse_list(self, **inputs):
        items = inputs[f"{self.KIND}_list"]
        count = MEDIA_SLOTS[self.KIND]
        return tuple(items[index] if index < len(items) else ExecutionBlocker(None) for index in range(count))


class YtonImageListParser(_MediaListParser):
    KIND = "image"
    RETURN_TYPES = ("IMAGE",) * 9
    RETURN_NAMES = tuple(f"image_{index}" for index in range(1, 10))


class YtonVideoListParser(_MediaListParser):
    KIND = "video"
    RETURN_TYPES = ("VIDEO",) * 3
    RETURN_NAMES = ("video_1", "video_2", "video_3")


class YtonAudioListParser(_MediaListParser):
    KIND = "audio"
    RETURN_TYPES = ("AUDIO",) * 3
    RETURN_NAMES = ("audio_1", "audio_2", "audio_3")


class YtonImageParser:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE", {"forceInput": True})}}

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    FUNCTION = "parse_image"
    CATEGORY = "yton-nodes/Media/解析"

    def parse_image(self, image):
        mask = 1.0 - image[..., 3] if image.shape[-1] == 4 else torch.zeros(image.shape[:3], dtype=image.dtype, device=image.device)
        return image[..., :3], mask


class YtonVideoParser:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video": ("VIDEO", {"forceInput": True})}}

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "parse_video"
    CATEGORY = "yton-nodes/Media/解析"

    def parse_video(self, video):
        return (video,)


class YtonAudioParser:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio": ("AUDIO", {"forceInput": True})}}

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "parse_audio"
    CATEGORY = "yton-nodes/Media/解析"

    def parse_audio(self, audio):
        return (audio,)
