import { app } from "../../../scripts/app.js";
import { mountNodePanel } from "./node_panel.js";

const stylesheet = document.createElement("link");
stylesheet.rel = "stylesheet";
stylesheet.href = new URL("../css/input_switch.css", import.meta.url).href;
document.head.append(stylesheet);

app.registerExtension({
  name: "yton.input.switch",
  nodeCreated(node) {
    if (node.comfyClass === "YtonInputSwitch") setupInputSwitch(node);
  },
});

export function setupInputSwitch(node) {
  const enabled = node.widgets.find(widget => widget.name === "enabled");
  function configureInput() {
    // The state is controlled by the segments, so its native widget socket is
    // not a second wire input (including an invisible clickable socket).
    const stateInput = node.inputs.findIndex(slot => slot.name === "enabled");
    if (stateInput >= 0) node.removeInput(stateInput);
    node.inputs[0].label = "输入";
  }
  configureInput();
  enabled.type = "hidden";
  enabled.hidden = true;
  enabled.computeSize = () => [0, 0];
  enabled.computeLayoutSize = () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
  enabled.draw = () => {};
  if (enabled.options) enabled.options.hidden = true;

  const panel = document.createElement("div");
  panel.className = "yton-input-switch";
  const segments = document.createElement("div");
  segments.className = "yton-input-switch-segments";
  segments.setAttribute("role", "group");
  segments.setAttribute("aria-label", "输入开关");
  panel.append(segments);
  const buttons = [true, false].map(value => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = value ? "开启" : "关闭";
    button.onclick = () => {
      if (enabled.value === value) return;
      node.graph?.beforeChange();
      enabled.value = value;
      enabled.callback?.(value);
      node.graph?.afterChange();
      node.setDirtyCanvas(true, true);
    };
    segments.append(button);
    return [value, button];
  });

  function render() {
    for (const [value, button] of buttons) button.setAttribute("aria-pressed", String(enabled.value === value));
  }
  // LiteGraph owns node colours; using its current values also follows the
  // native colour menu, workflow restore, and global palette changes.
  function syncColours() {
    panel.style.setProperty("--yton-switch-bg", node.bgcolor || LiteGraph.NODE_DEFAULT_BGCOLOR);
    panel.style.setProperty("--yton-switch-fg", node.title_text_color || LiteGraph.NODE_TEXT_COLOR);
  }
  const callback = enabled.callback;
  enabled.callback = function () {
    const result = callback?.apply(this, arguments);
    render();
    return result;
  };
  const configure = node.onConfigure;
  node.onConfigure = function () {
    const result = configure?.apply(this, arguments);
    configureInput();
    render();
    syncColours();
    return result;
  };
  const drawBackground = node.onDrawBackground;
  node.onDrawBackground = function () {
    const result = drawBackground?.apply(this, arguments);
    syncColours();
    return result;
  };
  render();
  syncColours();
  mountNodePanel(node, "input_switch_ui", panel, 210, 48);
}
