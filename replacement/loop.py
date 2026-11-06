"""Expand sequential segment executions and carry saved video into the next plan."""

import json

from comfy_api.latest import io
from comfy_execution.graph_utils import GraphBuilder, is_link

from .media import input_path


def expand_segments(hidden, plan, segments, loop_generation):
    prompt = hidden.dynprompt.get_original_prompt()
    root_id = hidden.unique_id
    children = {node_id: set() for node_id in prompt}
    for child_id, node in prompt.items():
        for value in node.get("inputs", {}).values():
            if is_link(value) and value[0] in children:
                children[value[0]].add(child_id)
    descendants, pending = set(), [root_id]
    while pending:
        for child_id in children.get(pending.pop(), ()):
            if child_id not in descendants:
                descendants.add(child_id)
                pending.append(child_id)
    if not descendants or (not loop_generation and plan["index"] == 0):
        return None

    save_ids = [node_id for node_id in descendants if prompt[node_id]["class_type"] == "YtonReplacementVideoSave"]
    if len(save_ids) > 1:
        raise ValueError("一份内置循环配置只能连接一个【人物替换 · 循环视频保存】。")
    if not loop_generation and not save_ids:
        return None

    import nodes
    output_nodes = []
    for node_id in descendants:
        class_type = prompt[node_id]["class_type"]
        if getattr(nodes.NODE_CLASS_MAPPINGS[class_type], "OUTPUT_NODE", False):
            output_nodes.append(node_id)
        if class_type in ("StartLoop", "EndLoop"):
            raise ValueError("使用内置循环时，请移除工作流中的官方循环开始、结束节点。")
    if not output_nodes:
        raise ValueError("循环生成需要连接到输出节点。")

    graph = GraphBuilder()
    previous_barrier = previous_video = None
    stop = plan["total"] if loop_generation else plan["index"] + 1
    for position, index in enumerate(range(plan["index"], stop)):
        if position == 0 and index > 0 and save_ids:
            save_id = save_ids[0]
            save_inputs = prompt[save_id]["inputs"]
            prefix = save_inputs["filename_prefix"]
            if is_link(prefix) and prefix[0] in descendants:
                if prompt[prefix[0]]["class_type"] != plan.get("parser_type", "YtonReplacementSegment") or prefix[1] != 9:
                    raise ValueError("重跑片段时，保存目录请连接配置解析器的项目目录，或使用固定目录。")
                config = json.loads(plan["config"])
                prefix = f"{plan.get('project_prefix', 'video/人物替换')}/%date:yyyy-MM-dd%/{input_path(config['video']).stem}/"
            previous_video = graph.node("YtonReplacementPreviousSegment", "previous",
                filename_prefix=prefix, reuse_existing=save_inputs.get("reuse_existing", False),
                index=index, total=plan["total"], save_id=save_id).out(0)
        step = graph.node(plan.get("loop_step_type", "YtonReplacementLoopStep"), f"step_{position}",
            plan={**plan, "index": index, "segment": segments[index]},
            previous_video=previous_video, dependency=previous_barrier)
        copies = {}
        for node_id in descendants:
            copied = graph.node(prompt[node_id]["class_type"], f"{position}_{node_id}")
            copied.set_override_display_id(node_id)
            copies[node_id] = copied
        for node_id, copied in copies.items():
            for name, value in hidden.dynprompt.get_node(node_id).get("inputs", {}).items():
                if is_link(value):
                    source_id, socket = value
                    if source_id == root_id:
                        value = step.out(socket)
                    elif source_id in copies:
                        value = copies[source_id].out(socket)
                copied.set_input(name, value)

        dependencies = {}
        for dependency_index, output_id in enumerate(output_nodes):
            output_def = nodes.NODE_CLASS_MAPPINGS[prompt[output_id]["class_type"]]
            outputs = getattr(output_def, "RETURN_TYPES", None)
            if outputs is None:
                outputs = getattr(getattr(output_def, "SCHEMA", None), "outputs", ())
            if not outputs:
                raise ValueError("循环中的输出节点需要提供输出端口，以确保每段执行完成。")
            dependencies[f"dependency{dependency_index}"] = copies[output_id].out(0)
        previous_barrier = graph.node("YtonReplacementLoopBarrier", f"barrier_{position}",
            start_id=root_id, position=index + 1, total=plan["total"], **dependencies).out(0)
        previous_video = copies[save_ids[0]].out(0) if save_ids else None
    hidden.execution_list.inhibit_nodes(descendants)
    return io.NodeOutput(None, expand=graph.finalize())
