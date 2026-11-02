"""Standalone image-frame adapter for the shared H3 face refinement graph."""

from comfy_api.latest import io
from comfy_execution.graph_utils import GraphBuilder

from .omni_face import add_face_refinement


class YtonH3FaceRefine(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="YtonH3FaceRefine",
            display_name="H3 小脸修复",
            category="yton-nodes/MiniMax H3",
            enable_expand=True,
            description=(
                "复用全模态生成节点的小脸修复：图片帧输入、图片帧输出，原音频继续走原连线。"
                "使用 H3 ref2va 模型、对应 CLIP 与视频 VAE；参考图可选。"
                "检测、跟踪、采样器和拼回设置内置；关闭时直接输出原图片帧，不加载修脸模型。"
            ),
            search_aliases=["修脸", "人脸", "face refine", "H3"],
            inputs=[
                io.Image.Input("images", display_name="图片帧", raw_link=True),
                io.Model.Input("model", display_name="修脸模型", optional=True, raw_link=True, lazy=True,
                    tooltip="H3 ref2va MODEL，可连接主模型或单独叠加 LoRA 的修脸模型。"),
                io.Clip.Input("clip", display_name="H3 CLIP", optional=True, raw_link=True, lazy=True),
                io.Vae.Input("vae", display_name="H3 视频 VAE", optional=True, raw_link=True, lazy=True),
                io.Autogrow.Input("references", display_name="人物参考图", optional=True,
                    template=io.Autogrow.TemplateNames(
                        io.Image.Input("reference", raw_link=True, lazy=True,
                            tooltip="人物参考图；连线后自动增加下一个入口，按连接顺序对应 <Picture N>。"),
                        names=[f"参考图 {i}" for i in range(1, 10)], min=0)),
                io.Custom("H3_PGS_ASSETS").Input("assets", display_name="参考素材集合", optional=True, lazy=True,
                    tooltip="与首采、二采共用图片参考顺序，保留 <Picture N> 的对应关系。"),
                io.String.Input("prompt", display_name="提示词", default="", multiline=True, raw_link=True, lazy=True,
                    tooltip="可接原提示词，也可填写修脸描述；留空依靠原画面与参考图修复。"),
                io.Boolean.Input("enabled", display_name="启用修脸", default=True),
                io.Int.Input("face_count", display_name="修脸人数", default=1, min=1, max=20),
                io.MultiType.Input(io.String.Input("sigmas", display_name="修脸 Sigma", default="",
                    tooltip="手填或连接 STRING / SIGMAS。留空使用内部 4 步、降噪 0.4；外接时间表按原值采样。"),
                    types=[io.String, io.Sigmas], lazy=True),
                io.Boolean.Input("reverse", display_name="倒序修脸", default=False),
            ],
            outputs=[io.Image.Output(display_name="修复后图片帧")],
        )

    @classmethod
    def check_lazy_status(cls, enabled=True, sigmas=None, **inputs):
        needed = ["sigmas"] if enabled and sigmas is None else []
        if enabled and "assets" in inputs and inputs["assets"] is None:
            needed.append("assets")
        return needed

    @classmethod
    def execute(cls, images, model=None, clip=None, vae=None, prompt="", enabled=True, face_count=1,
                sigmas="", reverse=False, references=None, assets=None):
        graph = GraphBuilder()
        if not enabled:
            return io.NodeOutput(images, expand=graph.finalize())
        if model is None or clip is None or vae is None:
            raise ValueError("启用修脸时，请连接修脸模型、H3 CLIP 和 H3 视频 VAE。")
        if isinstance(sigmas, str):
            sigmas = graph.node("ManualSigmas", id="face_sigmas", sigmas=sigmas).out(0) if sigmas.strip() else None
        pictures = list((assets or {}).get("images", []))
        pictures.extend(value for value in (references or {}).values() if value is not None)
        ref_images = {f"ref_image_{i}": value for i, value in enumerate(pictures)}
        frames = add_face_refinement(
            graph, images, None, model, clip, vae, None, None, prompt, "match",
            face_count, 4, 0.4, "bbox\\face_yolov8m.pt", reverse, 42, sigmas, 0.35, "none",
            ref_images=ref_images,
        )
        return io.NodeOutput(frames, expand=graph.finalize())


NODE_CLASS_MAPPINGS = {"YtonH3FaceRefine": YtonH3FaceRefine}
NODE_DISPLAY_NAME_MAPPINGS = {"YtonH3FaceRefine": "H3 小脸修复"}
