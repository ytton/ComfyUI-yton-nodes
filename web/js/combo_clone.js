import { app } from "../../../scripts/app.js";
import { comboChoices, comboTargets, commonComboChoices } from "./combo_options.js";

const TYPE = "YtonComboClone";

function refresh(node) {
  const connections = comboTargets(node);
  if (!connections.length) return;
  const values = commonComboChoices(connections);
  const widget = node.widgets.find(w => w.name === "value");
  const { target, input } = connections[0];
  const original = target.widgets?.find(w => w.name === input.widget?.name || w.name === input.name);
  widget.options.values = values;
  if (!values.includes(widget.value)) widget.value = values.includes(original?.value) ? original.value : values[0];
  widget.label = input.label || input.name;
  node.outputs[0].label = input.label || input.name;
  node.setDirtyCanvas(true, true);
}

app.registerExtension({
  name: "yton.ComboClone",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== TYPE) return;
    nodeData.output[0] = "COMBO";
    const connect = nodeType.prototype.onConnectOutput;
    nodeType.prototype.onConnectOutput = function (slot, type, input, target) {
      if (!Array.isArray(comboChoices(input)) || !commonComboChoices([...comboTargets(this), { target, input }]).length) return false;
      return connect?.apply(this, arguments);
    };
    const changed = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function (side, slot, connected) {
      const result = changed?.apply(this, arguments);
      if (side === LiteGraph.OUTPUT) refresh(this);
      return result;
    };
    const serialize = nodeType.prototype.onSerialize;
    nodeType.prototype.onSerialize = function () {
      refresh(this);
      return serialize?.apply(this, arguments);
    };
  },
  afterConfigureGraph() {
    for (const node of app.graph._nodes) if (node.comfyClass === TYPE) refresh(node);
  },
});
