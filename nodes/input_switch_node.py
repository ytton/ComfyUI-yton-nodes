"""Route an unchanged input to one of two mutually exclusive branches."""
from comfy_execution.graph_utils import ExecutionBlocker


class YtonInputSwitch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "value": ("*", {"forceInput": True}),
                "enabled": ("BOOLEAN", {"default": True, "label_on": "开启", "label_off": "关闭"}),
            },
        }

    RETURN_TYPES = ("*", "*")
    RETURN_NAMES = ("开启", "关闭")
    FUNCTION = "route"
    CATEGORY = "yton-nodes/Logic"
    DESCRIPTION = "将任意输入原样送到所选输出；另一条分支停止执行。控制开关可连接 BOOLEAN，未连接时使用节点上的开启／关闭按钮。"

    def route(self, value, enabled):
        blocked = ExecutionBlocker(None)
        return (value, blocked) if enabled else (blocked, value)
