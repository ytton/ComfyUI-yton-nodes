"""H3 generation and reference nodes registered by ComfyUI-yton-nodes."""
from . import omni_runtime, omni_context, omni_video_context_runtime, omni_guide, face_runtime, sampling_runtime, reference_runtime

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
for module in [omni_runtime, omni_context, omni_video_context_runtime, omni_guide, face_runtime, sampling_runtime, reference_runtime]:
    NODE_CLASS_MAPPINGS.update(module.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(module.NODE_DISPLAY_NAME_MAPPINGS)
