"""Release the H3 text encoder after all conditioning needed for sampling is ready."""

import comfy.model_management as model_management
from comfy.patcher_extension import WrappersMP
from comfy_api.latest import io


class YtonH3PrepareSampling(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="YtonH3PrepareSampling",
            display_name="H3 采样前调度",
            category="yton-nodes/MiniMax H3/内部",
            is_dev_only=True,
            inputs=[
                io.Model.Input("model"),
                io.Clip.Input("clip"),
                io.Conditioning.Input("conditioning"),
                io.Conditioning.Input("additional_conditioning", optional=True),
            ],
            outputs=[io.Model.Output()],
        )

    @classmethod
    def execute(cls, model, clip, conditioning, additional_conditioning=None):
        # Conditioning inputs wait for all reference encodes before sampling.
        text_encoder = clip.patcher

        def release_text_encoder(executor, *args, **kwargs):
            model_management.unload_model_and_clones(text_encoder)
            return executor(*args, **kwargs)

        patched = model.clone()
        patched.remove_wrappers_with_key(WrappersMP.OUTER_SAMPLE, "yton_h3_release_te")
        patched.add_wrapper_with_key(WrappersMP.OUTER_SAMPLE, "yton_h3_release_te", release_text_encoder)
        return io.NodeOutput(patched)


NODE_CLASS_MAPPINGS = {"YtonH3PrepareSampling": YtonH3PrepareSampling}
NODE_DISPLAY_NAME_MAPPINGS = {"YtonH3PrepareSampling": "H3 采样前调度"}
