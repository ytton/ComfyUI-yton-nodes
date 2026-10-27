"""Expose the original Niko H3 nodes alongside MultiRef without name collisions.

All node implementations are imported unchanged from the installed upstream
pack. No generation, sampling, or ComfyUI-core behavior is implemented here.
"""

import importlib.util
from pathlib import Path
import sys
import types

_upstream = Path(__file__).resolve().parents[2] / "ComfyUI-H3-Motion-Context"
if not (_upstream / "nodes.py").is_file():
    raise ImportError("Install NikoDemon80/ComfyUI-H3-Motion-Context first")

_package_name = "yuan_h3_niko_upstream"
_package = types.ModuleType(_package_name)
_package.__path__ = [str(_upstream)]
sys.modules[_package_name] = _package
_spec = importlib.util.spec_from_file_location(
    _package_name + ".nodes", _upstream / "nodes.py"
)
_nodes = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _nodes
_spec.loader.exec_module(_nodes)


class NikoMotionContext(_nodes.MiniMaxH3MotionContext):
    @classmethod
    def INPUT_TYPES(cls):
        schema = _nodes.MiniMaxH3MotionContext.INPUT_TYPES()
        # Normalize the UI control to the shared integer frame-count input.
        # Upstream apply() already converts context_length to int; unchanged.
        schema["required"]["context_length"] = (
            "INT", {"default": 39, "min": 5, "max": 56, "step": 17,
                    "tooltip": "Niko 原版支持 5 / 22 / 39 / 56 帧。"}
        )
        return schema

NODE_CLASS_MAPPINGS = {
    "YuanH3NikoMotionContext": NikoMotionContext,
    "YuanH3NikoMotionContextTrim": _nodes.MiniMaxH3MotionContextTrim,
    "YuanH3NikoSaveLatent": _nodes.MiniMaxH3MotionContextSaveLatent,
    "YuanH3NikoLoadLatent": _nodes.MiniMaxH3MotionContextLoadLatent,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "YuanH3NikoMotionContext": "H3 Motion Context · Niko 原版",
    "YuanH3NikoMotionContextTrim": "H3 Motion Context Trim · Niko 原版",
    "YuanH3NikoSaveLatent": "H3 Save AV Latent · Niko 原版",
    "YuanH3NikoLoadLatent": "H3 Load AV Latent · Niko 原版",
}
