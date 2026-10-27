"""
ComfyUI-yton-nodes entry point.
"""
from .nodes.resolution_node import YtonResolutionSelector, YtonResolutionSelectorSimple
from .nodes.media_loader_node import (
    YtonEasyMediaLoader, YtonImageListParser, YtonVideoListParser,
    YtonAudioListParser, YtonImageParser, YtonVideoParser, YtonAudioParser,
)
from .nodes.minimax_h3_reference_node import YtonMiniMaxH3ReferenceToVideo
from .nodes.h3_video_replacement_node import YtonH3VideoReplacementPrepare, YtonH3VideoReplacementTrim

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
    "YtonH3VideoReplacementPrepare": YtonH3VideoReplacementPrepare,
    "YtonH3VideoReplacementTrim": YtonH3VideoReplacementTrim,
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
    "YtonH3VideoReplacementPrepare": "H3 人物替换 · 参考视频补齐",
    "YtonH3VideoReplacementTrim": "H3 人物替换 · 声画同步裁尾",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

# H3 application adapters share the yton node package.
from .h3_director import (
    NODE_CLASS_MAPPINGS as _h3_classes,
    NODE_DISPLAY_NAME_MAPPINGS as _h3_names,
)
NODE_CLASS_MAPPINGS.update(_h3_classes)
NODE_DISPLAY_NAME_MAPPINGS.update(_h3_names)
