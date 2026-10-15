"""
ComfyUI-yton-nodes entry point.
"""
from .nodes.resolution_node import YtonResolutionSelector, YtonResolutionSelectorSimple
from .nodes.media_loader_node import (
    YtonEasyMediaLoader, YtonImageListParser, YtonVideoListParser,
    YtonAudioListParser, YtonImageParser, YtonVideoParser, YtonAudioParser,
)
from .nodes.minimax_h3_reference_node import YtonMiniMaxH3ReferenceToVideo

NODE_CLASS_MAPPINGS = {
    "YtonResolutionSelector": YtonResolutionSelector,
    "YtonResolutionSelectorSimple": YtonResolutionSelectorSimple,
    "YtonEasyMediaLoader": YtonEasyMediaLoader,
    "YtonImageListParser": YtonImageListParser,
    "YtonVideoListParser": YtonVideoListParser,
    "YtonAudioListParser": YtonAudioListParser,
    "YtonImageParser": YtonImageParser,
    "YtonVideoParser": YtonVideoParser,
    "YtonAudioParser": YtonAudioParser,
    "YtonMiniMaxH3ReferenceToVideo": YtonMiniMaxH3ReferenceToVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "YtonResolutionSelector": "分辨率比例控件",
    "YtonResolutionSelectorSimple": "分辨率比例控件simple",
    "YtonEasyMediaLoader": "媒体加载器",
    "YtonImageListParser": "图片列表解析",
    "YtonVideoListParser": "视频列表解析",
    "YtonAudioListParser": "音频列表解析",
    "YtonImageParser": "图片解析",
    "YtonVideoParser": "视频解析",
    "YtonAudioParser": "音频解析",
    "YtonMiniMaxH3ReferenceToVideo": "MiniMax H3 参考生成视频",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
