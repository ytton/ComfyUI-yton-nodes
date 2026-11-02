"""Native V3 nodes for replacement configuration and loop output."""

import json

from comfy_api.latest import io, ui

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
            description="配置视频、参考图片与提示词，并按当前索引直接输出媒体、提示词、尺寸和片段信息；索引从 0 开始。",
            inputs=[io.Int.Input("index", default=0, min=0, force_input=True, display_name="当前索引"),
                    io.Custom("YTON_LLM").Input("llm", optional=True, display_name="LLM 连接器"),
                    io.String.Input("config", default=json.dumps(DEFAULT_CONFIG, ensure_ascii=False), socketless=True)],
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
    def execute(cls, index, config, llm=None):
        config = parse_config(config)
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
            cache = execution_state(cls.hidden.dynprompt, cls.hidden.unique_id)["prompts"]
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
                    io.String.Input("config", default=json.dumps(DEFAULT_CONFIG, ensure_ascii=False), socketless=True)],
            outputs=[io.Custom("YTON_REPLACEMENT_PLAN").Output(display_name="分段配置"),
                     io.Int.Output(display_name="片段总数", tooltip="根据视频长度、选取范围和分段设置计算的总段数。")])

    @classmethod
    def fingerprint_inputs(cls, **inputs):
        return float("nan")

    @classmethod
    def execute(cls, config, llm=None):
        _, plan = plan_for(parse_config(config))
        return io.NodeOutput({"config": config, "llm": llm}, len(plan["segments"]))


class YtonReplacementSegment(YtonCharacterReplacement):
    @classmethod
    def define_schema(cls):
        schema = super().define_schema()
        schema.node_id = "YtonReplacementSegment"
        schema.display_name = "人物替换配置解析器"
        schema.description = "接收整合后的分段配置，按当前索引输出视频、参考图片、提示词、尺寸和片段信息；索引从 0 开始。"
        schema.inputs = [io.Int.Input("index", default=0, min=0, force_input=True, display_name="当前索引"),
                         io.Custom("YTON_REPLACEMENT_PLAN").Input("plan", display_name="分段配置")]
        return schema

    @classmethod
    def execute(cls, index, plan):
        return super().execute(index, plan["config"], plan["llm"])


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
                    io.Boolean.Input("save_full", default=True, display_name="保存完整视频")],
            outputs=[io.Video.Output(display_name="视频", tooltip="保存完成后传出输入的视频，可接循环结束节点，确保每轮先完成保存。")],
            is_output_node=True, hidden=[io.Hidden.unique_id, io.Hidden.dynprompt])

    @classmethod
    def fingerprint_inputs(cls, **inputs):
        return float("nan")

    @classmethod
    def execute(cls, video, current, total, filename_prefix, container, fps, crf, save_full):
        state = execution_state(cls.hidden.dynprompt, cls.hidden.unique_id)
        result = save_segment(video, current, total, run=state["run"], prefix=filename_prefix,
                              container=container, fps=fps, crf=crf, save_full=save_full)
        files = [result["saved_segment"]]
        if save_full and result["merged"]:
            files.append(result["merged"])
        return io.NodeOutput(video, ui={**ui.PreviewVideo(files).as_dict(), "replacement_saved": [result]})


CLASSES = [YtonLLMConnector, YtonCharacterReplacement, YtonReplacementPlan, YtonReplacementSegment, YtonReplacementVideoSave]
