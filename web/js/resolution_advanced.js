import { app } from "../../../scripts/app.js";
import { mountNodePanel, followNodeColours } from "./node_panel.js";

const stylesheet = document.createElement("link");
stylesheet.rel = "stylesheet";
stylesheet.href = new URL("../css/resolution_advanced.css", import.meta.url).href;
document.head.append(stylesheet);

const H3 = "MiniMax H3 (Video)";
const NORMAL = "Normal (Standard Image/Video)";
const RATIOS = ["auto", "16:9", "9:16", "1:1", "4:3", "3:4", "2:3", "3:2", "21:9"];
const RESOLUTIONS = {
  [H3]: ["320p", "480p", "540p", "640p", "720p", "768p", "944p", "1024p", "1080p", "2K", "4K"],
  [NORMAL]: ["480p", "540p", "640p", "720p", "1080p", "2K", "2.5K", "4K", "6K"],
};
const MP_MAP = {
  "320p": "0.3",
  "480p": "0.4",
  "540p": "0.5",
  "640p": "0.7",
  "720p": "0.9",
  "768p": "1.0",
  "944p": "1.5",
  "1024p": "1.8",
  "1080p": "2.0",
  "2K": "1.5",
  "4K": "2.5",
};
const INPUTS = [["width", "宽度"], ["height", "高度"], ["aspect_ratio", "比例"], ["resolution", "分辨率"], ["image", "图片"]];
const OUTPUTS = [["width", "宽度"], ["height", "高度"], ["aspect_ratio", "比例"], ["max_side", "长边"], ["min_side", "短边"], ["h3_mp", "H3 倍率"], ["resolution_str", "分辨率名称"]];
const REGIONS = [["mode", "模式切换"], ["resolutions", "分辨率区域"], ["ratios", "比例区域"], ["dimensions", "自定义宽高区域"]];
const DEFAULT_INPUTS = { width: false, height: false, aspect_ratio: true, resolution: false, image: true };
const DEFAULT_REGIONS = { mode: true, resolutions: true, ratios: true, dimensions: false };
const EYE = visible => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>${visible ? "" : '<path d="m3 3 18 18"/>'}</svg>`;
const GEAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 3-.6 2.4-2 .9L4.2 5.6 2 9.4l1.8 1.7v2L2 14.8l2.2 3.8 2.2-.7 2 .9L9 21h4l.6-2.2 2-.9 2.2.7 2.2-3.8-1.8-1.7v-2L20 9.4l-2.2-3.8-2.2.7-2-.9L13 3Z"/><circle cx="11" cy="12" r="3"/></svg>';

app.registerExtension({
  name: "yton.resolution.advanced",
  nodeCreated(node) {
    if (node.comfyClass === "YtonResolutionSelectorAdvanced") setupAdvancedResolution(node);
  },
});

function element(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text) result.textContent = text;
  return result;
}

export function setupAdvancedResolution(node) {
  const widgets = Object.fromEntries(node.widgets.map(widget => [widget.name, widget]));
  function exposeInputSlots() {
    for (const [name] of INPUTS) {
      const slot = node.inputs.find(input => input.name === name);
      // These sockets have their own custom controls. They must not depend on
      // a hidden native widget's hover state or layout row to be connectable.
      slot.widget = undefined;
      slot.alwaysVisible = true;
    }
  }
  for (const [name] of INPUTS) if (widgets[name]) node.convertWidgetToInput(widgets[name]);
  exposeInputSlots();
  for (const widget of node.widgets) {
    widget.type = "hidden";
    widget.hidden = true;
    widget.computeSize = () => [0, 0];
    widget.computeLayoutSize = () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
    widget.draw = () => {};
    if (widget.options) widget.options.hidden = true;
    if (widget.element) widget.element.style.display = "none";
  }

  let config;
  function readConfig() {
    const saved = JSON.parse(widgets.ui_config.value || "{}");
    config = {
      inputs: { ...DEFAULT_INPUTS, ...saved.inputs },
      outputs: { ...Object.fromEntries(OUTPUTS.map(([name]) => [name, true])), ...saved.outputs },
      regions: { ...DEFAULT_REGIONS, ...saved.regions },
      modes: saved.modes || {},
    };
  }
  readConfig();

  const panel = element("div", "yton-panel yton-resolution-panel yton-resolution-advanced");
  const header = element("div", "yton-header-row");
  header.append(element("div", "yton-title", "画幅与分辨率"));
  const modes = element("div", "yton-segmented");
  const modeButtons = [[H3, "MiniMax H3"], [NORMAL, "普通 / 图片"]].map(([value, label]) => {
    const button = element("button", "yton-segment-btn", label);
    button.type = "button";
    button.onclick = () => change(() => {
      widgets.mode.value = value;
      const options = visibleOptions("resolutions");
      if (!options.includes(widgets.resolution.value)) widgets.resolution.value = options[0] || RESOLUTIONS[value][0];
    });
    modes.append(button);
    return [value, button];
  });
  header.append(modes);
  panel.append(header);

  function section(name, label, gridClass) {
    const root = element("div", "yton-section");
    root.dataset.region = name;
    const title = element("div", "yton-label", label);
    const body = element("div", gridClass);
    root.append(title, body);
    panel.append(root);
    return { root, title, body };
  }
  const resolutions = section("resolutions", "输出分辨率", "yton-grid-pills");
  const ratios = section("ratios", "画面比例", "yton-grid-ratios");
  const dimensions = section("dimensions", "自定义宽高", "yton-advanced-dimensions");
  const sizeFields = INPUTS.slice(0, 2).map(([name, label]) => {
    const field = element("label", "yton-advanced-size-field");
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.max = "16384";
    input.step = "1";
    input.setAttribute("aria-label", label);
    input.title = "0 表示按预设或比例计算";
    input.onchange = () => {
      if (!input.checkValidity()) { input.reportValidity(); return; }
      change(() => { widgets[name].value = Number(input.value); });
    };
    field.append(element("span", "", label), input);
    dimensions.body.append(field);
    return [name, input];
  });

  const footer = element("div", "yton-resolution-footer");
  const settings = element("button", "yton-resolution-settings");
  settings.type = "button";
  settings.title = "配置输入、输出和显示区域";
  settings.setAttribute("aria-label", settings.title);
  settings.setAttribute("aria-expanded", "false");
  settings.innerHTML = GEAR;
  const popover = element("div", "yton-resolution-popover yton-advanced-popover");
  popover.popover = "auto";
  popover.setAttribute("aria-label", "高级控件设置");
  popover.append(element("strong", "", "高级控件设置"));
  const tabs = element("div", "yton-advanced-tabs");
  tabs.setAttribute("role", "tablist");
  const settingsBody = element("div", "yton-resolution-settings-list");
  settingsBody.setAttribute("role", "tabpanel");
  let activeTab = "ports";
  for (const [value, label] of [["ports", "输入 / 输出"], ["regions", "区域"], ["presets", "预设选项"]]) {
    const tab = element("button", "", label);
    tab.type = "button";
    tab.setAttribute("role", "tab");
    tab.dataset.tab = value;
    tab.onclick = () => { activeTab = value; renderSettings(); };
    tabs.append(tab);
  }
  popover.append(tabs, settingsBody);
  footer.append(settings, popover);
  panel.append(footer);

  const linked = name => node.inputs.some(input => input.name === name && input.link != null);
  const outputLinked = name => node.outputs.some(output => output.name === name && output.links?.length);
  function visibleOptions(kind) {
    const options = kind === "ratios" ? RATIOS : RESOLUTIONS[widgets.mode.value];
    const hidden = config.modes[widgets.mode.value]?.[kind] || [];
    return options.filter(value => !hidden.includes(value));
  }

  // Keep canonical slot indices in the graph/API. Only the layout and drawing
  // lists are filtered; hiding a middle output must never change link values.
  const slotVisible = (slot, isInput) => isInput ? config.inputs[slot.name] || slot.link != null : config.outputs[slot.name] || slot.links?.length;
  function visibleSlots(slots, isInput) {
    return slots.filter(slot => {
      if (slotVisible(slot, isInput)) return true;
      // Native hit testing still walks the canonical inputs/outputs. Clear the
      // old hit area so a hidden slot cannot overlap a compacted visible row.
      slot.boundingRect[0] = slot.boundingRect[1] = Number.NaN;
      slot.boundingRect[2] = slot.boundingRect[3] = 0;
      return false;
    });
  }
  const setConcreteSlots = node._setConcreteSlots;
  node._setConcreteSlots = function () {
    setConcreteSlots.apply(this, arguments);
    this._concreteInputs = visibleSlots(this._concreteInputs, true);
    this._concreteOutputs = visibleSlots(this._concreteOutputs, false);
  };
  const connectionPos = node.getConnectionPos;
  node.getConnectionPos = function (isInput, index, out) {
    const result = connectionPos.call(this, isInput, index, out);
    if (this.flags.collapsed || index < 0) return result;
    const slots = isInput ? this.inputs : this.outputs;
    const visible = slots.filter(slot => slotVisible(slot, isInput));
    const row = visible.indexOf(slots[index]);
    if (row < 0) {
      result[0] = result[1] = Number.NaN;
      return result;
    }
    result[1] = this.pos[1] + (row + .7) * LiteGraph.NODE_SLOT_HEIGHT + (this.constructor.slot_start_y || 0);
    return result;
  };
  // Mouse-down and link-drop code use these accessors rather than the drawing
  // rectangles. Resolve them through the same visible rows as rendered links.
  node.getInputPos = function (index) { return this.getConnectionPos(true, index); };
  node.getOutputPos = function (index) { return this.getConnectionPos(false, index); };
  // Drawing and hit testing must use the same compact positions as links.
  // LiteGraph's getOutputPos otherwise keeps the unfiltered output row.
  node._measureSlot = function (slot, index, isInput) {
    const slots = isInput ? this.inputs : this.outputs;
    const position = this.getConnectionPos(isInput, slots.indexOf(slot));
    const height = LiteGraph.NODE_SLOT_HEIGHT;
    slot.boundingRect[0] = position[0] - height / 2;
    slot.boundingRect[1] = position[1] - height / 2;
    slot.boundingRect[2] = height;
    slot.boundingRect[3] = height;
  };
  const computeSize = node.computeSize;
  node.computeSize = function () {
    const result = computeSize.apply(this, arguments);
    const full = Math.max(this.inputs.length, this.outputs.length, 1);
    const visible = Math.max(this.inputs.filter(slot => config.inputs[slot.name] || slot.link != null).length, this.outputs.filter(slot => config.outputs[slot.name] || slot.links?.length).length, 1);
    result[1] -= (full - visible) * LiteGraph.NODE_SLOT_HEIGHT;
    return result;
  };

  function change(mutate) {
    node.graph?.beforeChange();
    mutate();
    widgets.ui_config.value = JSON.stringify(config);
    render();
    node.graph?.afterChange();
  }
  function heading(label) { settingsBody.append(element("div", "yton-label", label)); }
  function toggle(label, visible, apply, disabled = false, detail = "") {
    const row = element("div", "yton-resolution-option-row");
    row.append(element("span", "", label));
    const button = element("button");
    button.type = "button";
    button.innerHTML = EYE(visible);
    button.setAttribute("aria-label", `${visible ? "隐藏" : "显示"} ${label}`);
    button.setAttribute("aria-pressed", String(visible));
    button.title = detail || button.getAttribute("aria-label");
    button.disabled = disabled;
    button.onclick = () => change(() => apply(!visible));
    row.append(button);
    settingsBody.append(row);
  }
  function renderSettings() {
    for (const tab of tabs.children) tab.setAttribute("aria-selected", String(tab.dataset.tab === activeTab));
    settingsBody.replaceChildren();
    if (activeTab === "ports") {
      heading("输入端口");
      for (const [name, label] of INPUTS) toggle(`${label}输入`, config.inputs[name] || linked(name), value => { config.inputs[name] = value; }, linked(name), linked(name) ? "请先断开连接，再隐藏该输入" : "");
      heading("输出端口");
      for (const [name, label] of OUTPUTS) toggle(`${label}输出`, config.outputs[name] || outputLinked(name), value => { config.outputs[name] = value; }, outputLinked(name), outputLinked(name) ? "请先断开连接，再隐藏该输出" : "");
    } else if (activeTab === "regions") {
      heading("区域显示与输入端口独立");
      for (const [name, label] of REGIONS) toggle(label, config.regions[name], value => { config.regions[name] = value; });
    } else {
      heading(widgets.mode.value === H3 ? "MiniMax H3 · 预设选项" : "普通 / 图片 · 预设选项");
      for (const [kind, label, widgetName, options] of [["resolutions", "分辨率", "resolution", RESOLUTIONS[widgets.mode.value]], ["ratios", "画面比例", "aspect_ratio", RATIOS]]) {
        heading(label);
        const visible = visibleOptions(kind);
        for (const value of options) toggle(value === "auto" ? "自动" : value, visible.includes(value), enabled => {
          const mode = config.modes[widgets.mode.value] ??= {};
          const hidden = mode[kind] || [];
          mode[kind] = enabled ? hidden.filter(item => item !== value) : [...hidden, value];
          if (!enabled && widgets[widgetName].value === value && !linked(widgetName)) widgets[widgetName].value = visibleOptions(kind)[0];
        }, visible.includes(value) && visible.length === 1, visible.length === 1 ? "至少保留一个预设；隐藏整个区域请在“区域”中设置" : "");
      }
    }
  }

  function render() {
    modes.hidden = !config.regions.mode;
    for (const [value, button] of modeButtons) {
      button.classList.toggle("active", widgets.mode.value === value);
      button.setAttribute("aria-pressed", String(widgets.mode.value === value));
    }
    resolutions.root.hidden = !config.regions.resolutions;
    resolutions.title.textContent = linked("resolution") ? "输出分辨率 · 跟随输入" : "输出分辨率";
    resolutions.body.replaceChildren();
    for (const value of visibleOptions("resolutions")) {
      const button = element("button", "yton-pill-btn", value);
      button.type = "button";
      button.classList.toggle("active", widgets.resolution.value === value);
      button.setAttribute("aria-pressed", String(widgets.resolution.value === value));
      button.disabled = linked("resolution");
      if (widgets.mode.value === H3 && MP_MAP[value]) {
        button.append(element("span", "yton-subtext", `(${MP_MAP[value]})`));
      }
      button.onclick = () => change(() => { widgets.resolution.value = value; });
      resolutions.body.append(button);
    }
    ratios.root.hidden = !config.regions.ratios;
    ratios.title.textContent = linked("aspect_ratio") ? "画面比例 · 跟随输入" : "画面比例";
    ratios.body.replaceChildren();
    for (const value of visibleOptions("ratios")) {
      const button = element("button", "yton-ratio-card");
      button.type = "button";
      button.setAttribute("aria-label", `画面比例 ${value === "auto" ? "自动" : value}`);
      if (value === "auto") button.title = "按输入图片匹配最接近的预设比例；未接图片时使用 16:9";
      button.setAttribute("aria-pressed", String(widgets.aspect_ratio.value === value));
      button.classList.toggle("active", widgets.aspect_ratio.value === value);
      button.disabled = linked("aspect_ratio");
      const icon = element("div", "yton-ratio-icon");
      const [w, h] = value === "auto" ? [1, 1] : value.split(":").map(Number);
      icon.style.width = `${24 * Math.min(1, w / h)}px`;
      icon.style.height = `${24 * Math.min(1, h / w)}px`;
      if (value === "auto") { icon.classList.add("yton-ratio-auto"); icon.textContent = "A"; }
      button.append(icon, element("div", "yton-ratio-text", value === "auto" ? "自动" : value));
      button.onclick = () => change(() => { widgets.aspect_ratio.value = value; });
      ratios.body.append(button);
    }
    dimensions.root.hidden = !config.regions.dimensions;
    for (const [name, input] of sizeFields) { input.value = widgets[name].value; input.disabled = linked(name); }
    if (popover.matches(":popover-open")) renderSettings();
    node.setDirtyCanvas(true, true);
  }

  settings.onclick = () => {
    if (popover.matches(":popover-open")) { popover.hidePopover(); return; }
    renderSettings();
    popover.showPopover();
    const bounds = panel.closest("[data-node-id]")?.getBoundingClientRect() || panel.getBoundingClientRect();
    const width = popover.offsetWidth;
    const right = bounds.right + 12;
    popover.style.left = `${Math.max(8, Math.min(right + width < innerWidth ? right : bounds.left - width - 12, innerWidth - width - 8))}px`;
    popover.style.top = `${Math.max(8, Math.min(bounds.top, innerHeight - popover.offsetHeight - 8))}px`;
  };
  popover.addEventListener("toggle", () => settings.setAttribute("aria-expanded", String(popover.matches(":popover-open"))));

  for (const widget of Object.values(widgets)) {
    const callback = widget.callback;
    widget.callback = function () {
      const result = callback?.apply(this, arguments);
      if (widget === widgets.ui_config) readConfig();
      render();
      return result;
    };
  }
  const configure = node.onConfigure;
  node.onConfigure = function () {
    const result = configure?.apply(this, arguments);
    exposeInputSlots();
    readConfig();
    render();
    return result;
  };
  const connections = node.onConnectionsChange;
  node.onConnectionsChange = function () {
    const result = connections?.apply(this, arguments);
    queueMicrotask(render);
    return result;
  };
  render();
  followNodeColours(node, panel);
  mountNodePanel(node, "advanced_resolution_ui", panel, 360, 310, { fitHeight: true });
}
