"""
Media loader node for images, audio, and video assets with strict quota enforcement.
"""
import os
import json
import torch
import numpy as np
from PIL import Image, ImageOps
from typing import Dict, Any, Tuple, List, Optional
import folder_paths

def empty_image_tensor() -> torch.Tensor:
    """Returns a dummy 1x1x3 empty float tensor [B, H, W, C]"""
    return torch.zeros((1, 64, 64, 3), dtype=torch.float32)

def empty_audio_dict() -> Dict[str, Any]:
    """Returns an empty audio structure compatible with ComfyUI Audio nodes"""
    return {"waveform": torch.zeros((1, 1, 1024), dtype=torch.float32), "sample_rate": 44100}

def load_image_tensor(filepath: str) -> torch.Tensor:
    """Load image from disk and return torch tensor in ComfyUI format [B, H, W, C]"""
    if not os.path.exists(filepath):
        return empty_image_tensor()
    try:
        img = Image.open(filepath)
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")
        image_np = np.array(img).astype(np.float32) / 255.0
        return torch.from_numpy(image_np)[None, ...]
    except Exception as e:
        print(f"[yton-nodes] Failed to load image {filepath}: {e}")
        return empty_image_tensor()

def load_audio_dict(filepath: str) -> Dict[str, Any]:
    """Load audio from disk using torchaudio or return dummy structure"""
    if not os.path.exists(filepath):
        return empty_audio_dict()
    try:
        import torchaudio
        waveform, sample_rate = torchaudio.load(filepath)
        return {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}
    except Exception as e:
        print(f"[yton-nodes] Audio loading fallback for {filepath}: {e}")
        return empty_audio_dict()


class YtonEasyMediaLoader:
    """
    Unified Media Loader supporting multi-image, audio, and video assets
    with client-side UI and server-side quota validation.
    """

    MAX_IMAGES = 9
    MAX_AUDIOS = 3
    MAX_VIDEOS = 3

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                # JSON string containing array of media items:
                # [{"type": "image"|"audio"|"video", "filename": "...", "subfolder": "...", "duration": 24}]
                "media_manifest": ("STRING", {
                    "default": "[]",
                    "multiline": True,
                }),
                "image_limit": ("INT", {"default": 9, "min": 0, "max": 16, "step": 1}),
                "audio_limit": ("INT", {"default": 3, "min": 0, "max": 8, "step": 1}),
                "video_limit": ("INT", {"default": 3, "min": 0, "max": 8, "step": 1}),
            },
            "optional": {
                "strict_quota_error": ("BOOLEAN", {"default": False, "label_on": "Throw Error", "label_off": "Auto Truncate"}),
            }
        }

    RETURN_TYPES = (
        "MEDIA_BUNDLE",  # Dictionary containing all lists and metadata
        "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", # 9 image slots
        "AUDIO", "AUDIO", "AUDIO", # 3 audio slots
        "STRING", "STRING", "STRING", # 3 video path slots
        "INT", "INT", "INT" # counts
    )

    RETURN_NAMES = (
        "media_bundle",
        "image_1", "image_2", "image_3", "image_4", "image_5", "image_6", "image_7", "image_8", "image_9",
        "audio_1", "audio_2", "audio_3",
        "video_1_path", "video_2_path", "video_3_path",
        "image_count", "audio_count", "video_count"
    )

    FUNCTION = "load_media"
    CATEGORY = "yton-nodes/Media"

    def load_media(
        self,
        media_manifest: str,
        image_limit: int,
        audio_limit: int,
        video_limit: int,
        strict_quota_error: bool = False
    ) -> Tuple:
        try:
            items = json.loads(media_manifest) if media_manifest.strip() else []
        except Exception:
            items = []

        images_info: List[Dict[str, Any]] = []
        audios_info: List[Dict[str, Any]] = []
        videos_info: List[Dict[str, Any]] = []

        for item in items:
            mtype = item.get("type", "").lower()
            if mtype == "image":
                images_info.append(item)
            elif mtype == "audio":
                audios_info.append(item)
            elif mtype == "video":
                videos_info.append(item)

        # Quota validation
        if strict_quota_error:
            if len(images_info) > image_limit:
                raise ValueError(f"[yton-nodes] Image count ({len(images_info)}) exceeded limit ({image_limit})")
            if len(audios_info) > audio_limit:
                raise ValueError(f"[yton-nodes] Audio count ({len(audios_info)}) exceeded limit ({audio_limit})")
            if len(videos_info) > video_limit:
                raise ValueError(f"[yton-nodes] Video count ({len(videos_info)}) exceeded limit ({video_limit})")
        else:
            images_info = images_info[:image_limit]
            audios_info = audios_info[:audio_limit]
            videos_info = videos_info[:video_limit]

        input_dir = folder_paths.get_input_directory()

        # Resolve paths
        def resolve_path(info: Dict[str, Any]) -> str:
            filename = info.get("filename", "")
            subfolder = info.get("subfolder", "")
            if subfolder:
                return os.path.join(input_dir, subfolder, filename)
            return os.path.join(input_dir, filename)

        # Load image tensors
        loaded_images: List[torch.Tensor] = []
        for info in images_info:
            full_path = resolve_path(info)
            loaded_images.append(load_image_tensor(full_path))

        # Load audio dicts
        loaded_audios: List[Dict[str, Any]] = []
        for info in audios_info:
            full_path = resolve_path(info)
            loaded_audios.append(load_audio_dict(full_path))

        # Video paths
        loaded_videos: List[str] = [resolve_path(info) for info in videos_info]

        # Prepare 9 image slots
        img_slots: List[torch.Tensor] = []
        for i in range(self.MAX_IMAGES):
            if i < len(loaded_images):
                img_slots.append(loaded_images[i])
            else:
                img_slots.append(empty_image_tensor())

        # Prepare 3 audio slots
        audio_slots: List[Dict[str, Any]] = []
        for i in range(self.MAX_AUDIOS):
            if i < len(loaded_audios):
                audio_slots.append(loaded_audios[i])
            else:
                audio_slots.append(empty_audio_dict())

        # Prepare 3 video slots
        video_slots: List[str] = []
        for i in range(self.MAX_VIDEOS):
            if i < len(loaded_videos):
                video_slots.append(loaded_videos[i])
            else:
                video_slots.append("")

        media_bundle = {
            "images": loaded_images,
            "audios": loaded_audios,
            "video_paths": loaded_videos,
            "raw_manifest": items,
            "counts": {
                "images": len(loaded_images),
                "audios": len(loaded_audios),
                "videos": len(loaded_videos)
            }
        }

        return (
            media_bundle,
            img_slots[0], img_slots[1], img_slots[2], img_slots[3], img_slots[4],
            img_slots[5], img_slots[6], img_slots[7], img_slots[8],
            audio_slots[0], audio_slots[1], audio_slots[2],
            video_slots[0], video_slots[1], video_slots[2],
            len(loaded_images), len(loaded_audios), len(loaded_videos)
        )
