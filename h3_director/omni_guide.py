"""Inject replacement keyframes through native H3 Add Guide."""

from comfy_api.latest import io
from comfy_extras.nodes_minimax_h3 import MiniMaxH3AddGuide


class YtonH3AnchorGuide(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonH3AnchorGuide", is_dev_only=True,
            inputs=[io.Conditioning.Input("positive"), io.Latent.Input("latent"), io.Vae.Input("vae"),
                    io.Custom("YTON_H3_ANCHORS").Input("anchor_images"), io.Int.Input("frame_offset", default=0)],
            outputs=[io.Conditioning.Output()])

    @classmethod
    def execute(cls, positive, latent, vae, anchor_images, frame_offset=0):
        for anchor in anchor_images:
            frame, image = anchor["frame"], anchor["image"]
            if not isinstance(frame, int) or frame < 0 or image.ndim != 4 or image.shape[0] != 1:
                raise ValueError("关键帧需要单张替换图片及非负帧序号。")
            positive = MiniMaxH3AddGuide.execute(positive, latent, frame + frame_offset,
                                                vae=vae, image=image).result[0]
        return io.NodeOutput(positive)


NODE_CLASS_MAPPINGS = {"YtonH3AnchorGuide": YtonH3AnchorGuide}
NODE_DISPLAY_NAME_MAPPINGS = {"YtonH3AnchorGuide": "H3 关键帧注入"}
