"""H3 application adapters registered by ComfyUI-yton-nodes."""
import logging
from pathlib import Path

from . import source_runtime, tracking_runtime, context_runtime, omni_runtime, omni_context, omni_video_context_runtime, omni_guide, face_runtime, sampling_runtime, reference_runtime

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
for module in [source_runtime, tracking_runtime, context_runtime, omni_runtime, omni_context, omni_video_context_runtime, omni_guide, face_runtime, sampling_runtime, reference_runtime]:
    NODE_CLASS_MAPPINGS.update(module.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(module.NODE_DISPLAY_NAME_MAPPINGS)

if (Path(__file__).resolve().parents[2] / 'ComfyUI-H3-Motion-Context/nodes.py').is_file():
    from . import niko_alias
    NODE_CLASS_MAPPINGS.update(niko_alias.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(niko_alias.NODE_DISPLAY_NAME_MAPPINGS)
else:
    logging.info('[yton-nodes] 未安装 Niko Motion Context，未注册对应 H3 节点。')
