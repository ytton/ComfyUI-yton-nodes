"""Select a row of typed parameters with one shared output definition."""

import json
import math

from comfy_api.latest import io


MAX_FIELDS = 64
VALUE_TYPES = {"STRING", "INT", "FLOAT", "BOOLEAN"}
DEFAULT_CONFIG = json.dumps({
    "options": [{"id": "option_a", "label": "A"}, {"id": "option_b", "label": "B"}],
    "outputs": [],
    "values": {"option_a": {}, "option_b": {}},
}, ensure_ascii=False)


def read_configuration(config, selected):
    data = json.loads(config)
    options, outputs, values = data["options"], data["outputs"], data["values"]
    if not options:
        raise ValueError("至少配置一个模式选项。")
    if len(outputs) > MAX_FIELDS:
        raise ValueError(f"最多配置 {MAX_FIELDS} 个输出字段。")
    for items, title in [(options, "模式选项"), (outputs, "输出字段")]:
        ids = [item["id"] for item in items]
        labels = [item["label"].strip() for item in items]
        if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"{title}的标识重复或为空。")
        if any(not name for name in labels) or len(set(labels)) != len(labels):
            raise ValueError(f"{title}的名称重复或为空。")
    if any(field["type"] not in VALUE_TYPES for field in outputs):
        raise ValueError("输出类型仅支持文本、整数、小数和布尔值。")
    option_ids = {option["id"] for option in options}
    if selected not in option_ids:
        raise ValueError("当前选中的模式不存在。")
    field_ids = {field["id"] for field in outputs}
    if set(values) != option_ids:
        raise ValueError("每个模式必须配置一组参数值。")
    for option in options:
        row = values[option["id"]]
        if set(row) != field_ids:
            raise ValueError(f"模式「{option['label']}」的输出字段不完整。")
        for field in outputs:
            value = row[field["id"]]
            kind = field["type"]
            valid = (
                (kind == "STRING" and isinstance(value, str))
                or (kind == "BOOLEAN" and type(value) is bool)
                or (kind == "INT" and type(value) is int and abs(value) <= 9007199254740991)
                or (kind == "FLOAT" and type(value) in (int, float) and math.isfinite(value))
            )
            if not valid:
                raise ValueError(f"模式「{option['label']}」的「{field['label']}」不是有效的 {kind} 值。")
    return data


class YtonModeParameters(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="YtonModeParameters",
            display_name="模式参数映射",
            category="yton-nodes/逻辑",
            description="用分段器选择模式，统一输出该模式的文本、数值和布尔参数。右下角齿轮配置选项、输出和值；模式索引从 0 开始。",
            search_aliases=["模式", "映射", "combo", "preset", "mode parameters"],
            inputs=[
                io.String.Input("config", default=DEFAULT_CONFIG, socketless=True),
                io.String.Input("selected", default="option_a", socketless=True),
            ],
            # V3 declares output slots at registration time. The UI exposes only
            # configured fields, with concrete types, in the same result order.
            outputs=[io.String.Output(display_name="模式"), io.Int.Output(display_name="索引")]
            + [io.AnyType.Output(display_name=f"参数 {i + 1}") for i in range(MAX_FIELDS)],
        )

    @classmethod
    def execute(cls, config, selected):
        data = read_configuration(config, selected)
        index = next(i for i, option in enumerate(data["options"]) if option["id"] == selected)
        option = data["options"][index]
        row = data["values"][selected]
        result = [float(row[f["id"]]) if f["type"] == "FLOAT" else row[f["id"]] for f in data["outputs"]]
        return io.NodeOutput(option["label"], index, *result)
