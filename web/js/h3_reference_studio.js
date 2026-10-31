import { app } from "../../../scripts/app.js";
import { mountNodePanel } from "./node_panel.js";
import { setupMediaLoaderNode } from "./media_loader_panel.js";

const stylesheet = document.createElement("link");
stylesheet.rel = "stylesheet";
stylesheet.href = new URL("../css/h3_reference_studio.css", import.meta.url).href;
document.head.append(stylesheet);

const element = (tag, className, text) => {
  const item = document.createElement(tag);
  item.className = className;
  if (text) item.textContent = text;
  return item;
};
const TYPES = ["正向条件", "AV latent", "宽度", "高度", "帧数"];

function setupStudio(node) {
  const widgets = Object.fromEntries(node.widgets.map(w => [w.name, w]));
  const spec = node.constructor.nodeData.input.required;
  const presets = spec.resolution[1].yton_presets;
  const ratios = spec.aspect_ratio[1].options;
  const tiers = spec.resolution[1].options;
  node.convertWidgetToInput(widgets.prompt);
  const promptSlot = node.inputs.find(i => i.name === "prompt");
  promptSlot.widget = undefined;
  promptSlot.label = "提示词（可选连线）";
  for (const widget of node.widgets) {
    widget.type = "hidden"; widget.hidden = true;
    widget.computeSize = () => [0, 0];
    widget.computeLayoutSize = () => ({ minWidth: 0, minHeight: 0, maxHeight: 0 });
    widget.draw = () => {};
    widget.options.hidden = true;
    if (widget.element) widget.element.style.display = "none";
  }
  const panel = element("div", "yton-panel yton-h3-studio");
  // The output rail sits beside the panel and must not push that panel down
  // when LiteGraph measures sockets to find the widget starting position.
  node.widgets_start_y = 90;
  const controls = element("div", "yton-h3-controls");
  const mediaColumn = element("div", "yton-h3-media");
  const outputs = element("div", "yton-h3-outputs");
  panel.append(controls, mediaColumn, outputs);
  const groups = [];
  let refreshing = false;

  function update(name, value) {
    node.graph?.beforeChange();
    widgets[name].value = value;
    widgets[name].callback?.(value);
    node.graph?.afterChange();
    refresh();
  }
  function section(title, host = controls) {
    const root = element("section", "yton-h3-section");
    root.append(element("div", "yton-h3-heading", title));
    host.append(root);
    return root;
  }
  function segmented(name, options, host, label = v => v) {
    const group = element("div", "yton-h3-segments");
    group.setAttribute("role", "group"); group.setAttribute("aria-label", name);
    const buttons = options.map(value => {
      const button = element("button", "yton-h3-choice", label(value));
      button.type = "button"; button.dataset.value = value;
      button.onclick = () => update(name, value);
      group.append(button);
      return [value, button];
    });
    groups.push([name, buttons]); host.append(group);
    return group;
  }
  function customChoice(group, name, label, select) {
    const button = group.querySelector('[data-value="自定义"]');
    const tile = element("div", "yton-h3-custom-choice");
    button.replaceWith(tile); tile.append(button);
    const input = element("input", "");
    input.type = "number"; input.step = name === "duration" ? "0.1" : "0.05";
    input.min = spec[name][1].min; input.max = spec[name][1].max;
    input.setAttribute("aria-label", label);
    input.onfocus = () => select();
    input.onchange = () => {
      if (!input.checkValidity() || !input.value.trim()) { input.reportValidity(); return; }
      const value = Number(input.value);
      select(); update(name, value);
    };
    tile.append(input, element("span", "yton-h3-unit", name === "duration" ? "秒" : "×"));
    return input;
  }
  function number(name, label, host, step = 1) {
    const field = element("label", "yton-h3-number");
    const input = element("input", "");
    input.type = "number"; input.step = String(step);
    const inputSpec = spec[name][1];
    input.min = inputSpec.min; input.max = inputSpec.max;
    input.setAttribute("aria-label", label);
    input.onchange = () => {
      if (!input.checkValidity() || !input.value.trim()) { input.reportValidity(); return; }
      update(name, Number(input.value));
    };
    field.append(element("span", "", label), input); host.append(field);
    return input;
  }
  const promptSection = section("提示词");
  const prompt = element("textarea", "yton-h3-prompt");
  prompt.placeholder = "描述视频内容，可使用 <Picture 1>、<Video 1>、<Audio 1> 引用右侧素材";
  prompt.setAttribute("aria-label", "提示词");
  prompt.oninput = () => update("prompt", prompt.value);
  promptSection.append(prompt);

  const canvasSection = section("画幅与分辨率");
  const tiersGroup = segmented("resolution", tiers, canvasSection);
  tiersGroup.classList.add("yton-h3-tiers");
  const ratiosGroup = segmented("aspect_ratio", ratios, canvasSection, v => v === "auto" ? "自动" : v);
  ratiosGroup.classList.add("yton-h3-ratios");
  const customCanvas = element("div", "yton-h3-custom-canvas");
  const widthInput = number("custom_width", "宽度", customCanvas, 32);
  const heightInput = number("custom_height", "高度", customCanvas, 32);
  canvasSection.append(customCanvas);
  const sizeInfo = element("div", "yton-h3-size-info");
  canvasSection.append(sizeInfo);

  const refSection = section("参考图尺寸");
  refSection.title = "match：按输出像素面积缩小参考图；max：使用原生最大参考尺寸；自定义：在 match 基础上缩放宽高。";
  const refGroup = segmented("ref_image_size", ["max", "match", "自定义"], refSection);
  refGroup.classList.add("yton-h3-ref-size");
  const scaleInput = customChoice(refGroup, "ref_scale", "参考图缩放比例", () => {
    if (widgets.ref_image_size.value !== "自定义") update("ref_image_size", "自定义");
  });

  const durationSection = section("视频时长");
  const durationButtons = element("div", "yton-h3-segments");
  durationSection.append(durationButtons);
  const durationOptions = [3, 5, 7.5, 10, 15, "自定义"].map(value => {
    const button = element("button", "yton-h3-choice", value === "自定义" ? value : `${value} 秒`);
    button.type = "button";
    button.dataset.value = value;
    button.onclick = () => {
      node.properties.ytonDurationCustom = value === "自定义";
      if (value !== "自定义") update("duration", value);
      else { node.graph?.change(); refresh(); }
    };
    durationButtons.append(button); return [value, button];
  });
  durationButtons.classList.add("yton-h3-durations");
  const durationInput = customChoice(durationButtons, "duration", "自定义秒数", () => {
    node.properties.ytonDurationCustom = true; refresh();
  });
  const timeInfo = element("div", "yton-h3-size-info");
  durationSection.append(timeInfo);

  mediaColumn.append(element("div", "yton-h3-heading", "参考媒体"));
  const mediaPanel = setupMediaLoaderNode(node, { embedded: true, onChange: () => refresh() });
  mediaColumn.append(mediaPanel);
  mediaPanel.addEventListener("load", () => refresh(), true);

  outputs.append(element("div", "yton-h3-heading", "输出"));
  const outputRows = TYPES.map((name, index) => {
    const row = element("div", "yton-h3-output-row", name);
    node.outputs[index].label = " ";
    row.dataset.output = index; outputs.append(row); return row;
  });

  function dimensions(ratio = widgets.aspect_ratio.value, tier = widgets.resolution.value) {
    if (tier === "自定义") return [widgets.custom_width.value, widgets.custom_height.value].map(v => Math.max(32, Math.floor(v / 32) * 32));
    if (ratio === "auto") {
      const image = [...mediaColumn.querySelectorAll(".image-grid .has-media:not(.output-disabled) img")].find(img => img.naturalWidth);
      ratio = image ? ratios.filter(r => r !== "auto").reduce((best, r) => {
        const distance = value => { const [w, h] = value.split(":").map(Number); return Math.abs(Math.log((image.naturalWidth / image.naturalHeight) / (w / h))); };
        return distance(r) < distance(best) ? r : best;
      }, "16:9") : "16:9";
    }
    return presets[`${ratio}|${tier}`];
  }
  function refresh() {
    if (refreshing || !mediaColumn.isConnected) return;
    refreshing = true;
    const linked = node.inputs.find(i => i.name === "prompt")?.link != null;
    prompt.disabled = linked;
    if (document.activeElement !== prompt) prompt.value = widgets.prompt.value;
    prompt.title = linked ? "由提示词连线提供内容" : "";
    for (const [name, buttons] of groups) for (const [value, button] of buttons) {
      const active = widgets[name].value === value;
      button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active));
      if (name === "resolution" && value !== "自定义") {
        const [w, h] = dimensions(widgets.aspect_ratio.value, value);
        button.textContent = `${value} · ${(w * h / 1e6).toFixed(2)} MP`;
      }
    }
    customCanvas.hidden = widgets.resolution.value !== "自定义";
    scaleInput.parentElement.classList.toggle("active", widgets.ref_image_size.value === "自定义");
    for (const [input, name] of [[widthInput, "custom_width"], [heightInput, "custom_height"], [scaleInput, "ref_scale"], [durationInput, "duration"]]) {
      if (document.activeElement !== input) input.value = widgets[name].value;
    }
    const [width, height] = dimensions();
    sizeInfo.textContent = `${width} × ${height} · ${(width * height / 1e6).toFixed(2)} MP`;
    const custom = node.properties.ytonDurationCustom || !durationOptions.some(([v]) => v === widgets.duration.value);
    durationInput.parentElement.classList.toggle("active", Boolean(custom));
    for (const [value, button] of durationOptions) {
      const active = custom ? value === "自定义" : value === widgets.duration.value;
      button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active));
    }
    const frames = Math.ceil((Math.max(5, Math.ceil(widgets.duration.value * 24)) - 5) / 17) * 17 + 5;
    timeInfo.textContent = `${frames} 帧 · 实际 ${(frames / 24).toFixed(2)} 秒 · 24 fps`;
    timeInfo.title = "H3 按 17n + 5 帧向上对齐，输出帧数可直接连接后续视频节点。";
    node.setDirtyCanvas(true, true);
    refreshing = false;
  }
  const originalOutputPos = node.getConnectionPos;
  function outputY(index) {
    const row = outputRows[index];
    if (!row?.isConnected || !row.offsetHeight) return null;
    return node.pos[1] + 100 + row.offsetTop + row.offsetHeight / 2;
  }
  node.getConnectionPos = function (isInput, index, out) {
    const pos = originalOutputPos.call(this, isInput, index, out);
    if (!isInput && !this.flags.collapsed) {
      const y = outputY(index);
      if (y != null) { pos[0] = this.pos[0] + this.size[0] - 4; pos[1] = y; }
    }
    return pos;
  };
  const getOutputPos = node.getOutputPos;
  node.getOutputPos = function (index) {
    const y = !this.flags.collapsed && outputY(index);
    return y ? [this.pos[0] + this.size[0] - 4, y] : getOutputPos.call(this, index);
  };
  const measureSlot = node._measureSlot;
  node._measureSlot = function (slot, index, isInput) {
    const result = measureSlot.call(this, slot, index, isInput);
    if (!isInput) {
      const y = outputY(index);
      if (y != null) {
        const height = LiteGraph.NODE_SLOT_HEIGHT;
        slot.boundingRect[0] = this.pos[0] + this.size[0] - 4 - height / 2;
        slot.boundingRect[1] = y - height / 2;
        slot.boundingRect[2] = slot.boundingRect[3] = height;
      }
    }
    return result;
  };
  const configure = node.onConfigure;
  node.onConfigure = function () { const result = configure?.apply(this, arguments); requestAnimationFrame(refresh); return result; };
  const connections = node.onConnectionsChange;
  node.onConnectionsChange = function () { const result = connections?.apply(this, arguments); refresh(); return result; };
  for (const widget of Object.values(widgets).filter(w => !/^(disable_)?(image|video|audio)_\d+$/.test(w.name))) {
    const callback = widget.callback;
    widget.callback = function () { const result = callback?.apply(this, arguments); refresh(); return result; };
  }
  node.setSize([1080, node.size[1]]);
  const domWidget = mountNodePanel(node, "h3_reference_studio_ui", panel, 860, 560, { fitHeight: true });
  domWidget.options.canvasOnly = true;
  requestAnimationFrame(refresh);
}

app.registerExtension({ name: "yton.H3ReferenceStudio", nodeCreated(node) {
  if (node.comfyClass === "YtonH3ReferenceStudio") setupStudio(node);
} });
