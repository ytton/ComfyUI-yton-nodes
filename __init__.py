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

from .node_catalog import configure_node_catalog as _configure_node_catalog
from .nodes.weighted_lora_node import YtonWeightedLoraLoader
NODE_CLASS_MAPPINGS["YtonWeightedLoraLoader"] = YtonWeightedLoraLoader
NODE_DISPLAY_NAME_MAPPINGS["YtonWeightedLoraLoader"] = "权重 LoRA 加载器"
from .nodes.h3_reference_studio_node import YtonH3ReferenceStudio
NODE_CLASS_MAPPINGS["YtonH3ReferenceStudio"] = YtonH3ReferenceStudio
NODE_DISPLAY_NAME_MAPPINGS["YtonH3ReferenceStudio"] = "H3 参考视频工作台"
_configure_node_catalog(NODE_CLASS_MAPPINGS)

from .replacement.nodes import CLASSES as _replacement_classes
from .replacement.routes import install as _install_replacement_routes
for _node in _replacement_classes:
    _schema = _node.define_schema()
    NODE_CLASS_MAPPINGS[_schema.node_id] = _node
    NODE_DISPLAY_NAME_MAPPINGS[_schema.node_id] = _schema.display_name
_install_replacement_routes()
