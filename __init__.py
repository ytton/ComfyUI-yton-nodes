"""
ComfyUI-yton-nodes entry point.
"""
from .nodes.resolution_node import YtonResolutionSelector, YtonResolutionSelectorSimple
from .nodes.media_loader_node import YtonEasyMediaLoader

NODE_CLASS_MAPPINGS = {
    "YtonResolutionSelector": YtonResolutionSelector,
    "YtonResolutionSelectorSimple": YtonResolutionSelectorSimple,
    "YtonEasyMediaLoader": YtonEasyMediaLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "YtonResolutionSelector": "分辨率比例控件",
    "YtonResolutionSelectorSimple": "分辨率比例控件simple",
    "YtonEasyMediaLoader": "yton Easy 媒体加载器 (Media Loader)",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
