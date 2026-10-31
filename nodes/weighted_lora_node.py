"""An ordered LoRA stack with a connectable strength for each row."""

import json
import math

import folder_paths
from comfy_api.latest import io
from comfy_execution.graph_utils import GraphBuilder


class YtonWeightedLoraLoader(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="YtonWeightedLoraLoader",
            display_name="权重 LoRA 加载器",
            category="yton-nodes/模型",
            enable_expand=True,
            description="动态添加 LoRA，按列表顺序加载。每行左侧接口控制该行强度；未连线时使用行内数值。CLIP 可选，接入后使用相同强度。",
            search_aliases=["lora", "LoRA", "权重", "动态加载器"],
            inputs=[
                io.Model.Input("model", display_name="模型"),
                io.Clip.Input("clip", display_name="CLIP（可选）", optional=True),
                io.String.Input("loras", default="[]", socketless=True, extra_dict={
                    "yton_loras": folder_paths.get_filename_list("loras"),
                }),
                io.Autogrow.Input("strengths", optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        io.Float.Input("strength", min=-100, max=100, step=0.01),
                        prefix="strength_", min=0, max=100,
                    )),
            ],
            outputs=[io.Model.Output(display_name="模型"), io.Clip.Output(display_name="CLIP")],
        )

    @classmethod
    def execute(cls, model, loras, clip=None, strengths=None):
        rows = json.loads(loras)
        if not isinstance(rows, list):
            raise ValueError("LoRA 配置必须是列表。")
        strengths = strengths or {}
        graph = GraphBuilder()
        used_slots = set()
        for row in rows:
            slot = row["slot"]
            if type(slot) is not int or not 0 <= slot < 100 or slot in used_slots:
                raise ValueError("LoRA 行的强度接口编号无效或重复。")
            used_slots.add(slot)
            if not row["enabled"] or not row["lora"]:
                continue
            strength = float(strengths.get(f"strength_{slot}", row["strength"]))
            if not math.isfinite(strength):
                raise ValueError(f"LoRA 强度必须是有限数值：{row['lora']}")
            if strength == 0:
                continue
            folder_paths.get_full_path_or_raise("loras", row["lora"])
            if clip is None:
                loader = graph.node("LoraLoaderModelOnly", id=f"lora_{slot}", model=model,
                    lora_name=row["lora"], strength_model=strength)
            else:
                loader = graph.node("LoraLoader", id=f"lora_{slot}", model=model, clip=clip,
                    lora_name=row["lora"], strength_model=strength, strength_clip=strength)
                clip = loader.out(1)
            model = loader.out(0)
        return io.NodeOutput(model, clip, expand=graph.finalize())
