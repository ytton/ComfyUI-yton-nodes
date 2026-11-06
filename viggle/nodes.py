"""Viggle-specific configuration, parser and sequential plan."""

import json

from comfy_api.latest import io

from ..replacement.loop import expand_segments
from ..replacement.media import image_tensors, input_path, output_size
from ..replacement.prompts import prompt_slot, source_prompt
from ..replacement.save import execution_state
from .media import DEFAULT_CONFIG, parse_config, plan_for, references, segment, segment_metadata
from .prompts import optimize, resolve_references, signature


class YtonViggleReplacementPlan(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonViggleReplacementPlan", display_name="Viggle 人物替换配置器 · 配置输出",
            category="yton-nodes/Viggle", description="四张参考图或四个替换关键帧；内嵌选帧，分段上下文沿用视频编辑器的重叠帧数。",
            inputs=[io.Custom("YTON_LLM").Input("llm", optional=True, display_name="LLM 连接器"),
                    io.String.Input("config", default=json.dumps(DEFAULT_CONFIG, ensure_ascii=False), socketless=True),
                    io.Int.Input("selected_index", default=0, min=0, socketless=True),
                    io.Boolean.Input("loop_generation", default=False, socketless=True)],
            outputs=[io.Custom("YTON_VIGGLE_PLAN").Output(display_name="本段配置")],
            hidden=[io.Hidden.unique_id, io.Hidden.dynprompt, io.Hidden.execution_list], enable_expand=True)

    @classmethod
    def fingerprint_inputs(cls, **inputs):
        return float("nan")

    @classmethod
    def execute(cls, config, selected_index, loop_generation, llm=None):
        parsed = parse_config(config)
        _, plan = plan_for(parsed)
        index = max(0, min(selected_index, len(plan["segments"]) - 1))
        value = {"config": config, "llm": llm, "index": index, "total": len(plan["segments"]),
                 "segment": plan["segments"][index], "previous_video": None,
                 "loop_step_type": "YtonViggleLoopStep", "parser_type": "YtonViggleReplacementSegment",
                 "project_prefix": "video/Viggle"}
        execution_state(cls.hidden.dynprompt, cls.hidden.unique_id)
        expanded = expand_segments(cls.hidden, value, plan["segments"], loop_generation)
        return expanded if expanded is not None else io.NodeOutput(value)


class YtonViggleLoopStep(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonViggleLoopStep", is_dev_only=True,
            inputs=[io.Custom("YTON_VIGGLE_PLAN").Input("plan"),
                    io.Video.Input("previous_video", optional=True), io.AnyType.Input("dependency", optional=True)],
            outputs=[io.Custom("YTON_VIGGLE_PLAN").Output()])

    @classmethod
    def execute(cls, plan, previous_video=None, dependency=None):
        return io.NodeOutput({**plan, "previous_video": previous_video})


class YtonViggleReplacementSegment(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonViggleReplacementSegment", display_name="Viggle 人物替换配置解析器",
            category="yton-nodes/Viggle", description="按实际输入顺序输出四张参考图和零基 pins；视频先经过长度调整再送入 Conditioning。",
            inputs=[io.Custom("YTON_VIGGLE_PLAN").Input("plan", display_name="本段配置")],
            outputs=[io.Video.Output(display_name="原始片段"), io.String.Output(display_name="提示词"),
                     *[io.Image.Output(display_name=f"参考图 {i}") for i in range(1, 5)],
                     io.String.Output(display_name="pins"), io.Int.Output(display_name="短边尺寸"),
                     io.Int.Output(display_name="片段序号"), io.String.Output(display_name="项目目录"),
                     io.Int.Output(display_name="片段总数"), io.Custom("YTON_VIGGLE_SEGMENT").Output(display_name="片段信息"),
                     io.Int.Output(display_name="上下文长度（帧）", tooltip="当前段开头与上一段实际重叠的帧数；首段或切镜后不承接时为 0。"),
                     io.Boolean.Output(display_name="是否首段", tooltip="当前片段为整个分段计划的第一段时输出 true。")],
            hidden=[io.Hidden.unique_id, io.Hidden.dynprompt])

    @classmethod
    def fingerprint_inputs(cls, **inputs):
        return float("nan")

    @classmethod
    def execute(cls, plan):
        config, index = parse_config(plan["config"]), plan["index"]
        video, _ = segment(config, index)
        info, metadata, _ = segment_metadata(config, index)
        images, pins = references(config, index, plan["previous_video"])
        if not images:
            raise ValueError("请上传至少一张参考图或替换关键帧。")
        slot, digest = prompt_slot(config, index), signature(config, index)
        if config["auto"]:
            state = execution_state(cls.hidden.dynprompt, cls.hidden.unique_id)
            key = (index, digest, plan["llm"])
            if key not in state["prompts"]:
                state["prompts"][key] = optimize(plan["llm"], config, index, video, images, pins)
            text = state["prompts"][key]
        else:
            optimized = config["optimized"].get(slot, {})
            text = optimized["text"] if optimized.get("signature") == digest else source_prompt(config, index)
        text = resolve_references(text, config, index)
        tensors = image_tensors(images)
        tensors += [None] * (4 - len(tensors))
        width, height = output_size(config, metadata)
        prefix = f"video/Viggle/%date:yyyy-MM-dd%/{input_path(config['video']).stem}/"
        return io.NodeOutput(video, text, *tensors, pins, min(width, height), index + 1, prefix,
            info["total"], info, info["overlap_frames"], index == 0, ui={"viggle_prompt": [{"index": index, "slot": slot, "text": text,
                "signature": digest, "width": width, "height": height}]})


CLASSES = [YtonViggleReplacementPlan, YtonViggleReplacementSegment, YtonViggleLoopStep]
