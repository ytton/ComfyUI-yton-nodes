"""
ComfyUI-yton-nodes entry point.
"""
from .nodes.resolution_node import YtonResolutionSelector
from .nodes.media_loader_node import (
    YtonEasyMediaLoader, YtonImageListParser, YtonVideoListParser,
    YtonAudioListParser, YtonImageParser, YtonVideoParser, YtonAudioParser,
)

NODE_CLASS_MAPPINGS = {
    "YtonResolutionSelector": YtonResolutionSelector,
    "YtonEasyMediaLoader": YtonEasyMediaLoader,
    "YtonImageListParser": YtonImageListParser,
    "YtonVideoListParser": YtonVideoListParser,
    "YtonAudioListParser": YtonAudioListParser,
    "YtonImageParser": YtonImageParser,
    "YtonVideoParser": YtonVideoParser,
    "YtonAudioParser": YtonAudioParser,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "YtonResolutionSelector": "分辨率比例控件",
    "YtonEasyMediaLoader": "媒体加载器",
    "YtonImageListParser": "图片列表解析",
    "YtonVideoListParser": "视频列表解析",
    "YtonAudioListParser": "音频列表解析",
    "YtonImageParser": "图片解析",
    "YtonVideoParser": "视频解析",
    "YtonAudioParser": "音频解析",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
