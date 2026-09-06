"""
Media loader node with explicit standard inputs for easy JSON / API workflow manipulation.
"""
import os
import torch
import numpy as np
from PIL import Image, ImageOps
from typing import Dict, Any, Tuple, List
import folder_paths

def empty_image_tensor() -> torch.Tensor:
    return torch.zeros((1, 64, 64, 3), dtype=torch.float32)

def empty_audio_dict() -> Dict[str, Any]:
    return {"waveform": torch.zeros((1, 1, 1024), dtype=torch.float32), "sample_rate": 44100}

def load_image_tensor(filepath: str) -> torch.Tensor:
    if not filepath or not os.path.exists(filepath):
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
    if not filepath or not os.path.exists(filepath):
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
    Unified Media Loader supporting multi-image, audio, and video assets.
    Inputs are standard individual slots (image_1~9, audio_1~3, video_1~3)
    allowing seamless JSON / API modification from external software.
    """

    MAX_IMAGES = 9
    MAX_AUDIOS = 3
    MAX_VIDEOS = 3

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        required = {
            "image_limit": ("INT", {"default": 9, "min": 0, "max": 9, "step": 1}),
            "audio_limit": ("INT", {"default": 3, "min": 0, "max": 3, "step": 1}),
            "video_limit": ("INT", {"default": 3, "min": 0, "max": 3, "step": 1}),
        }

        # Explicit image inputs (filenames or paths relative to input folder)
        for i in range(1, cls.MAX_IMAGES + 1):
            required[f"image_{i}"] = ("STRING", {"default": "", "multiline": False})

        # Explicit audio inputs
        for i in range(1, cls.MAX_AUDIOS + 1):
            required[f"audio_{i}"] = ("STRING", {"default": "", "multiline": False})

        # Explicit video inputs
        for i in range(1, cls.MAX_VIDEOS + 1):
            required[f"video_{i}"] = ("STRING", {"default": "", "multiline": False})

        return {
            "required": required,
            "optional": {
                "strict_quota_error": ("BOOLEAN", {"default": False, "label_on": "Throw Error", "label_off": "Auto Truncate"}),
            }
        }

    RETURN_TYPES = (
        "MEDIA_BUNDLE",
        "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE",
        "AUDIO", "AUDIO", "AUDIO",
        "STRING", "STRING", "STRING",
        "INT", "INT", "INT"
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

    def _resolve_file_path(self, filename: str) -> str:
        if not filename or not filename.strip():
            return ""
        clean_name = filename.strip()
        # Direct absolute path
        if os.path.isabs(clean_name) and os.path.exists(clean_name):
            return clean_name
        # ComfyUI input folder
        input_dir = folder_paths.get_input_directory()
        candidate = os.path.join(input_dir, clean_name)
        if os.path.exists(candidate):
            return candidate
        return candidate

    def load_media(
        self,
        image_limit: int,
        audio_limit: int,
        video_limit: int,
        strict_quota_error: bool = False,
        **kwargs
    ) -> Tuple:
        raw_images = [kwargs.get(f"image_{i}", "").strip() for i in range(1, self.MAX_IMAGES + 1)]
        raw_audios = [kwargs.get(f"audio_{i}", "").strip() for i in range(1, self.MAX_AUDIOS + 1)]
        raw_videos = [kwargs.get(f"video_{i}", "").strip() for i in range(1, self.MAX_VIDEOS + 1)]

        # Filter active non-empty items
        active_images = [p for p in raw_images if p]
        active_audios = [p for p in raw_audios if p]
        active_videos = [p for p in raw_videos if p]

        # Quota validation
        if strict_quota_error:
            if len(active_images) > image_limit:
                raise ValueError(f"[yton-nodes] Image count ({len(active_images)}) exceeded limit ({image_limit})")
            if len(active_audios) > audio_limit:
                raise ValueError(f"[yton-nodes] Audio count ({len(active_audios)}) exceeded limit ({audio_limit})")
            if len(active_videos) > video_limit:
                raise ValueError(f"[yton-nodes] Video count ({len(active_videos)}) exceeded limit ({video_limit})")
        else:
            active_images = active_images[:image_limit]
            active_audios = active_audios[:audio_limit]
            active_videos = active_videos[:video_limit]

        # Load images
        loaded_image_tensors: List[torch.Tensor] = []
        for path in active_images:
            full_path = self._resolve_file_path(path)
            loaded_image_tensors.append(load_image_tensor(full_path))

        # Load audios
        loaded_audio_dicts: List[Dict[str, Any]] = []
        for path in active_audios:
            full_path = self._resolve_file_path(path)
            loaded_audio_dicts.append(load_audio_dict(full_path))

        # Video paths
        resolved_video_paths = [self._resolve_file_path(p) for p in active_videos]

        # Populate output slots
        img_slots = [loaded_image_tensors[i] if i < len(loaded_image_tensors) else empty_image_tensor() for i in range(self.MAX_IMAGES)]
        audio_slots = [loaded_audio_dicts[i] if i < len(loaded_audio_dicts) else empty_audio_dict() for i in range(self.MAX_AUDIOS)]
        video_slots = [resolved_video_paths[i] if i < len(resolved_video_paths) else "" for i in range(self.MAX_VIDEOS)]

        media_bundle = {
            "images": loaded_image_tensors,
            "audios": loaded_audio_dicts,
            "video_paths": resolved_video_paths,
            "counts": {
                "images": len(active_images),
                "audios": len(active_audios),
                "videos": len(active_videos)
            }
        }

        return (
            media_bundle,
            *img_slots,
            *audio_slots,
            *video_slots,
            len(active_images),
            len(active_audios),
            len(active_videos)
        )
