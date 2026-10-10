"""Fixed media slots and typed list/item parsers for ComfyUI."""

import os

import folder_paths
import numpy as np
import torch
from PIL import Image, ImageOps


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
                        alpha = np.array(source.getchannel("A"), dtype=np.float32) / 255.0 if "A" in source.getbands() else None
                    image = torch.from_numpy(rgb).unsqueeze(0)
                    # Keep standard IMAGE consumers on RGB. The item parser reads
                    # the slot's native editor mask from this same tensor.
                    if alpha is not None:
                        image.yton_mask = torch.from_numpy(1.0 - alpha).unsqueeze(0)
                    items.append(image)
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
    DESCRIPTION = "按有效素材顺序拆分列表。可提前连接全部输出，未填充的输出传递空值，由支持可选素材的下游节点忽略。"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {cls.KIND: (cls.KIND.upper(), {"forceInput": True})}}

    def parse_list(self, **inputs):
        items = inputs[self.KIND]
        count = MEDIA_SLOTS[self.KIND]
        # An execution blocker cancels the entire downstream call, including
        # its populated inputs. None lets optional-media consumers skip only
        # the missing item while keeping every socket connected.
        return tuple(items[index] if index < len(items) else None for index in range(count))


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
        if image is None:
            return None, None
        mask = getattr(image, "yton_mask", None)
        if mask is None:
            mask = 1.0 - image[..., 3] if image.shape[-1] == 4 else torch.zeros(image.shape[:3], dtype=image.dtype, device=image.device)
        return image[..., :3], mask


class YtonVideoParser:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video": ("VIDEO", {"forceInput": True}),
            "force_rate": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 120.0, "step": 1.0,
                                    "tooltip": "0 保留原帧率；H3 参考视频设为 24，按原时长重采样，不改变音轨速度。"}),
        }}

    RETURN_TYPES = ("IMAGE", "INT", "AUDIO", "VHS_VIDEOINFO")
    RETURN_NAMES = ("图像", "帧计数", "音频", "视频信息")
    FUNCTION = "parse_video"
    CATEGORY = "yton-nodes/Media/解析"
    DESCRIPTION = "解析视频画面、帧数、原音轨和 VHS 视频信息；可按原时长转换帧率。空视频透传空值，无音轨时音频为空。"

    def parse_video(self, video, force_rate=0.0):
        if video is None:
            return None, None, None, None
        components = video.get_components()
        images = components.images
        source_frame_count, height, width = map(int, images.shape[:3])
        source_fps = float(components.frame_rate)
        if not source_frame_count:
            raise ValueError("视频中没有可解析的图像帧")
        if source_fps <= 0:
            raise ValueError("视频帧率必须大于 0")
        fps = float(force_rate) if force_rate > 0 else source_fps
        if force_rate > 0:
            frame_count = max(1, int(source_frame_count / source_fps * fps))
            indexes = (torch.arange(frame_count, device=images.device) * source_fps / fps).long()
            images = images[indexes.clamp_max(source_frame_count - 1)]
        frame_count = int(images.shape[0])
        source_width, source_height = video.get_dimensions()
        video_info = {
            "source_fps": float(video.get_frame_rate()),
            # All input frames are decoded; container frame counts can be estimates.
            "source_frame_count": source_frame_count,
            "source_duration": float(video.get_duration()),
            "source_width": int(source_width),
            "source_height": int(source_height),
            "loaded_fps": fps,
            "loaded_frame_count": frame_count,
            "loaded_duration": frame_count / fps,
            "loaded_width": width,
            "loaded_height": height,
        }
        return images, frame_count, components.audio, video_info


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
