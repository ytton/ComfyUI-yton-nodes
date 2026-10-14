"""Export the edited node schemas for isolated browser checks before restart."""

import importlib.util
import json
from pathlib import Path
import sys

from comfy_api.latest import io

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("yton_preview", root / "__init__.py", submodule_search_locations=[str(root)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
definitions = {}
for name, node in package.NODE_CLASS_MAPPINGS.items():
    if issubclass(node, io.ComfyNode):
        definitions[name] = node.GET_NODE_INFO_V1()
        definitions[name]["python_module"] = "custom_nodes.ComfyUI-yton-nodes"
        continue
    inputs = node.INPUT_TYPES()
    definitions[name] = {
        "input": inputs,
        "input_order": {key: list(values) for key, values in inputs.items()},
        "output": node.RETURN_TYPES,
        "output_name": node.RETURN_NAMES,
        "output_is_list": getattr(node, "OUTPUT_IS_LIST", (False,) * len(node.RETURN_TYPES)),
        "input_is_list": getattr(node, "INPUT_IS_LIST", False),
        "name": name,
        "display_name": package.NODE_DISPLAY_NAME_MAPPINGS[name],
        "description": getattr(node, "DESCRIPTION", ""),
        "category": node.CATEGORY,
        "output_node": False,
        "python_module": "custom_nodes.ComfyUI-yton-nodes",
    }
target = root / "temp" / "node-definitions.json"
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(definitions, ensure_ascii=False), encoding="utf-8")
