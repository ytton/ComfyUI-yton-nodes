"""Expose a connected dropdown's selected value as a COMBO output."""

from comfy_api.latest import io


class YtonComboClone(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="YtonComboClone", display_name="下拉选项克隆",
            category="yton-nodes/逻辑",
            description="将 COMBO 输出连接到模型名称、采样器等下拉输入，自动读取目标的选项并输出选中值。多个目标共用时只显示它们共有的选项。",
            search_aliases=["combo clone", "下拉", "克隆"],
            inputs=[io.Combo.Input("value", options=["请先连接目标下拉输入"],
                                   display_name="选项", socketless=True)],
            # V1 dropdowns use a list as their backend type; the frontend
            # exposes COMBO while AnyType accepts both list and V3 enums.
            outputs=[io.AnyType.Output(display_name="下拉值")],
        )

    @classmethod
    def validate_inputs(cls, value):
        # The frontend obtains the available values from the connected input.
        return type(value) in (str, int)

    @classmethod
    def execute(cls, value):
        return io.NodeOutput(value)
