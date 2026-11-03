"""Native V3 nodes for replacement configuration and loop output."""

import json

from comfy_api.latest import io, ui
from comfy_execution.graph_utils import GraphBuilder, is_link
from server import PromptServer

from ..llm_connection import LLMConnection
from .media import image_tensors, input_path, inspect, output_size, plan_for, reference_images, segment_video
from .prompts import optimize, prompt_slot, resolve_references, signature, source_prompt
from .save import execution_state, save_segment


DEFAULT_CONFIG = {
    "video": "", "images": [""] * 6, "original": "将 <Video 1> 中的主体替换为 <Picture 1> 中的角色，动作与镜头沿用原视频。",
    "prompts": {}, "optimized": {}, "shared": False, "auto": False,
    "ratio": "原视频", "resolution": "480p", "image_scale": 1,
    "plan": {"enabled": False, "mode": "MiniMax H3", "frames": 175, "seconds": 5,
             "overlap": 22, "output": "完整片段", "start": 0, "end": 0},
    "crop": None, "compression": {"fps": 24, "crf": 18, "max_edge": 0,
                                    "width": 0, "height": 0, "resize_method": "pad"},
}


def parse_config(text):
    value = json.loads(text)
    if not isinstance(value, dict) or len(value["images"]) != 6:
        raise ValueError("人物替换配置需要一个视频和六个图片槽位。")
    return value


class YtonLLMConnector(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonLLMConnector", display_name="LLM 通用连接器", category="yton-nodes/AI",
            description="配置服务、模型和通用调用参数；任务指令由连接它的节点提供。",
            inputs=[io.String.Input("model_ref", default="", socketless=True),
                    io.Float.Input("temperature", default=0.7, min=0, max=2, step=0.05),
                    io.Int.Input("max_tokens", default=4096, min=128, max=131072, step=128)],
            outputs=[io.Custom("YTON_LLM").Output(display_name="LLM")])

    @classmethod
    def execute(cls, model_ref, temperature, max_tokens):
        return io.NodeOutput(LLMConnection(model_ref, temperature, max_tokens))


class YtonCharacterReplacement(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonCharacterReplacement", display_name="人物替换配置器 · 媒体输出", category="yton-nodes/媒体",
            description="未连接当前索引时，输出面板选中的片段；连接后按外部索引输出媒体、提示词、尺寸和片段信息，索引从 0 开始。",
            inputs=[io.Int.Input("index", min=0, optional=True, force_input=True, display_name="当前索引",
                                 tooltip="可选，从 0 开始。未连接时输出“片段提示词”中选中的片段；连接后以外部索引为准。"),
                    io.Custom("YTON_LLM").Input("llm", optional=True, display_name="LLM 连接器"),
                    io.String.Input("config", default=json.dumps(DEFAULT_CONFIG, ensure_ascii=False), socketless=True),
                    io.Int.Input("selected_index", default=0, min=0, optional=True, socketless=True)],
            outputs=[io.Image.Output(display_name="图片列表", is_output_list=True),
                     io.Video.Output(display_name="视频列表", is_output_list=True),
                     io.String.Output(display_name="提示词"),
                     io.Int.Output(display_name="宽度", tooltip="生成目标宽度，由节点的分辨率与画面比例决定，独立于参考视频压缩尺寸。"),
                     io.Int.Output(display_name="高度", tooltip="生成目标高度，由节点的分辨率与画面比例决定，独立于参考视频压缩尺寸。"),
                     io.Int.Output(display_name="长度（帧数）", tooltip="当前输出视频的实际帧数，尾段按剩余长度计算。"),
                     io.Float.Output(display_name="时长（秒）", tooltip="实际帧数除以输出帧率，可连接全模态生成节点的时长。"),
                     io.Int.Output(display_name="片段序号", tooltip="当前索引 + 1，从 1 开始；连接保存器的片段序号。"),
                     io.Int.Output(display_name="片段总数"),
                     io.String.Output(display_name="项目目录", tooltip="按源视频文件名生成保存前缀，可连接视频保存节点的保存目录 / 前缀。")],
            hidden=[io.Hidden.unique_id, io.Hidden.dynprompt])

    @classmethod
    def fingerprint_inputs(cls, **inputs):
        # Auto optimization runs once per queued execution, not once per browser session.
        return float("nan")

    @classmethod
    def execute(cls, config, llm=None, selected_index=0, index=None):
        state = execution_state(cls.hidden.dynprompt, cls.hidden.unique_id)
        config = parse_config(config)
        index = selected_index if index is None else index
        video, plan = segment_video(config, index)
        width, height = output_size(config, inspect(config["video"]))
        frames = video.get_frame_count()
        duration = float(frames / video.get_frame_rate())
        images = reference_images(config)
        slot = prompt_slot(config, index)
        source_signature = signature(config, index)
        if config["auto"]:
            if llm is None:
                raise ValueError("自动优化已开启，请连接【LLM 通用连接器】。")
            cache = state["prompts"]
            key = (slot, source_signature, llm)
            if key not in cache:
                cache[key] = optimize(llm, config, index, video, images)
            text = cache[key]
        else:
            result = config["optimized"].get(slot, {})
            text = result["text"] if result.get("signature") == source_signature else source_prompt(config, index)
        text = resolve_references(text, config)
        project_directory = f"video/人物替换/%date:yyyy-MM-dd%/{input_path(config['video']).stem}/"
        return io.NodeOutput(image_tensors(images), [video], text, width, height, frames, duration,
                             index + 1, len(plan["segments"]), project_directory,
                             ui={"replacement_prompt": [{"index": index, "slot": slot, "text": text,
                                  "signature": source_signature, "frames": plan["segments"][index]["end"] - plan["segments"][index]["start"],
                                  "total": len(plan["segments"]), "width": width, "height": height}]})


class YtonReplacementPlan(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonReplacementPlan", display_name="人物替换配置器 · 配置输出", category="yton-nodes/媒体",
            description="将视频、参考图片、提示词与分段设置整合为一份配置，并计算片段总数；连接【人物替换配置解析器】提取媒体。",
            inputs=[io.Custom("YTON_LLM").Input("llm", optional=True, display_name="LLM 连接器"),
                    io.String.Input("config", default=json.dumps(DEFAULT_CONFIG, ensure_ascii=False), socketless=True),
                    io.Int.Input("selected_index", default=0, min=0, optional=True, socketless=True),
                    io.Boolean.Input("loop_generation", default=False, socketless=True,
                                     tooltip="从当前选中片段开始，依次执行到最后一段。")],
            outputs=[io.Custom("YTON_REPLACEMENT_PLAN").Output(display_name="分段配置"),
                     io.Int.Output(display_name="片段总数", tooltip="根据视频长度、选取范围和分段设置计算的总段数。")],
            hidden=[io.Hidden.unique_id, io.Hidden.dynprompt, io.Hidden.execution_list], enable_expand=True)

    @classmethod
    def fingerprint_inputs(cls, **inputs):
        return float("nan")

    @classmethod
    def execute(cls, config, llm=None, selected_index=0, loop_generation=False):
        dynprompt = cls.hidden.dynprompt
        execution_state(dynprompt, cls.hidden.unique_id)
        parsed = parse_config(config)
        _, plan = plan_for(parsed)
        total = len(plan["segments"])
        selected_index = max(0, min(int(selected_index), total - 1))
        plan_value = {"config": config, "llm": llm, "selected_index": selected_index, "total": total}
        if not loop_generation or selected_index >= total - 1:
            return io.NodeOutput(plan_value, total)

        prompt = dynprompt.get_original_prompt()
        root_id = cls.hidden.unique_id
        children = {node_id: set() for node_id in prompt}
        for child_id, node in prompt.items():
            for value in node.get("inputs", {}).values():
                if is_link(value) and value[0] in children:
                    children[value[0]].add(child_id)
        descendants, pending = set(), [root_id]
        while pending:
            parent_id = pending.pop()
            for child_id in children.get(parent_id, ()):
                if child_id not in descendants:
                    descendants.add(child_id)
                    pending.append(child_id)
        if not descendants:
            return io.NodeOutput(plan_value, total)

        import nodes
        output_nodes = []
        for node_id in descendants:
            class_def = nodes.NODE_CLASS_MAPPINGS[prompt[node_id]["class_type"]]
            if getattr(class_def, "OUTPUT_NODE", False):
                output_nodes.append(node_id)
            if prompt[node_id].get("_loop_body") or prompt[node_id].get("_loop_end"):
                raise ValueError("人物替换内置循环暂不支持下游再嵌套官方循环。")
        if not output_nodes:
            raise ValueError("循环生成需要把配置输出连接到至少一个输出节点。")

        graph = GraphBuilder()
        previous_barrier = None
        for position, index in enumerate(range(selected_index, total)):
            step = graph.node("YtonReplacementLoopStep", f"step_{position}",
                              plan={**plan_value, "selected_index": index},
                              selected_index=index,
                              dependency=previous_barrier)
            copies = {}
            for node_id in descendants:
                original = dynprompt.get_node(node_id)
                copied = graph.node(original["class_type"], f"{position}_{node_id}")
                copied.set_override_display_id(root_id if original["class_type"] == "YtonReplacementSegment" else node_id)
                copies[node_id] = copied

            def copied_link(value):
                if not is_link(value):
                    return value
                source_id, socket = value
                if source_id == root_id:
                    if socket not in (0, 1):
                        raise ValueError("循环子图引用了配置输出中不支持的端口。")
                    return step.out(socket)
                if source_id in copies:
                    return copies[source_id].out(socket)
                return value

            for node_id, copied in copies.items():
                original = dynprompt.get_node(node_id)
                for name, value in original.get("inputs", {}).items():
                    copied.set_input(name, copied_link(value))
                if original["class_type"] == "YtonReplacementSegment":
                    copied.set_input("index", step.out(2))

            dependencies = {}
            for dependency_index, output_id in enumerate(output_nodes):
                output_def = nodes.NODE_CLASS_MAPPINGS[prompt[output_id]["class_type"]]
                outputs = getattr(output_def, "RETURN_TYPES", None)
                if outputs is None:
                    schema = getattr(output_def, "SCHEMA", None)
                    outputs = getattr(schema, "outputs", ())
                if not outputs:
                    raise ValueError("循环生成中的每个输出节点都需要提供输出端口，才能确保保存完成后再进入下一段。")
                dependencies[f"dependency{dependency_index}"] = copies[output_id].out(0)
            barrier = graph.node("YtonReplacementLoopBarrier", f"barrier_{position}",
                                 start_id=root_id, position=index + 1, total=total, **dependencies)
            previous_barrier = barrier.out(0)

        cls.hidden.execution_list.inhibit_nodes(descendants)
        return io.NodeOutput(None, None, expand=graph.finalize())


class YtonReplacementLoopStep(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonReplacementLoopStep", inputs=[
            io.Custom("YTON_REPLACEMENT_PLAN").Input("plan"),
            io.Int.Input("selected_index"),
            io.AnyType.Input("dependency", optional=True),
        ], outputs=[io.Custom("YTON_REPLACEMENT_PLAN").Output(), io.Int.Output(), io.Int.Output()], is_dev_only=True)

    @classmethod
    def execute(cls, plan, selected_index, dependency=None):
        return io.NodeOutput(plan, plan["total"], selected_index)


class YtonReplacementLoopBarrier(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonReplacementLoopBarrier", is_input_list=True,
            inputs=[io.String.Input("start_id"), io.Int.Input("position"), io.Int.Input("total")],
            outputs=[io.Int.Output()], is_output_node=True, is_dev_only=True, accept_all_inputs=True)

    @classmethod
    def execute(cls, start_id, position, total, **kwargs):
        PromptServer.instance.send_progress_text(f"人物替换片段 {position[0]} / {total[0]}", start_id[0])
        return io.NodeOutput(position[0])


class YtonReplacementSegment(YtonCharacterReplacement):
    @classmethod
    def define_schema(cls):
        schema = super().define_schema()
        schema.node_id = "YtonReplacementSegment"
        schema.display_name = "人物替换配置解析器"
        schema.description = "未连接当前索引时输出配置器选中的片段；连接后按外部索引输出视频、参考图片、提示词、尺寸和片段信息，索引从 0 开始。"
        schema.inputs = [io.Int.Input("index", min=0, optional=True, force_input=True, display_name="当前索引",
                                     tooltip="未连接时输出配置器面板选中的片段；连接后以外部索引为准，从 0 开始。"),
                         io.Custom("YTON_REPLACEMENT_PLAN").Input("plan", display_name="分段配置")]
        return schema

    @classmethod
    def execute(cls, plan, index=None):
        return super().execute(config=plan["config"], llm=plan["llm"], selected_index=plan["selected_index"], index=index)


class YtonReplacementVideoSave(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonReplacementVideoSave", display_name="人物替换 · 循环视频保存", category="yton-nodes/媒体",
            description="每轮保存片段；全部片段完成后按序合并。关闭完整视频保存时，合并视频仅放临时目录供预览。",
            inputs=[io.Video.Input("video", display_name="待保存视频"),
                    io.Int.Input("current", default=1, min=1, force_input=True, display_name="片段序号",
                                 tooltip="视频是第几段，从 1 开始；用于确定保存与合并顺序。"),
                    io.Int.Input("total", default=1, min=1, force_input=True, display_name="片段总数",
                                 tooltip="这一轮需要保存的片段数量；全部到齐后合并。"),
                    io.String.Input("filename_prefix", default="replacement/video", display_name="保存目录 / 前缀"),
                    io.Combo.Input("container", options=["mp4", "mkv"], default="mp4", display_name="格式 · H.264"),
                    io.Int.Input("fps", default=24, min=1, max=120, display_name="保存帧率"),
                    io.Int.Input("crf", default=18, min=0, max=51, display_name="质量 CRF"),
                    io.Boolean.Input("reuse_existing", default=False, display_name="覆盖最近项目中的本段"),
                    io.Boolean.Input("save_full", default=True, display_name="保存完整视频")],
            outputs=[io.Video.Output(display_name="视频", tooltip="保存完成后传出输入的视频，可接循环结束节点，确保每轮先完成保存。")],
            is_output_node=True, hidden=[io.Hidden.unique_id, io.Hidden.dynprompt])

    @classmethod
    def fingerprint_inputs(cls, **inputs):
        return float("nan")

    @classmethod
    def execute(cls, video, current, total, filename_prefix, container, fps, crf,
                reuse_existing=False, save_full=True):
        state = execution_state(cls.hidden.dynprompt, cls.hidden.unique_id)
        result = save_segment(video, current, total, run=state["run"], started_at=state["started_at"], prefix=filename_prefix,
                              container=container, fps=fps, crf=crf, reuse_existing=reuse_existing, save_full=save_full,
                              project_root=state.get("project_root"))
        state["project_root"] = result.pop("_project_root")
        files = [result["saved_segment"]]
        if save_full and result["merged"]:
            files.append(result["merged"])
        return io.NodeOutput(video, ui={**ui.PreviewVideo(files).as_dict(), "replacement_saved": [result]})


CLASSES = [YtonLLMConnector, YtonCharacterReplacement, YtonReplacementPlan, YtonReplacementSegment,
           YtonReplacementLoopStep, YtonReplacementLoopBarrier, YtonReplacementVideoSave]
