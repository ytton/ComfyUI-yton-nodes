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

function setupStudio(node) {
  const widgets = Object.fromEntries(node.widgets.map(w => [w.name, w]));
  const spec = node.constructor.nodeData.input.required;
  const presets = spec.resolution[1].yton_presets;
  const multipliers = spec.resolution[1].yton_h3_multipliers;
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
  const controls = element("div", "yton-h3-controls");
  const mediaColumn = element("div", "yton-h3-media");
  panel.append(controls, mediaColumn);
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
    button.replaceWith(tile);
    const input = element("input", "");
    input.type = "number"; input.step = name === "duration" ? "0.1" : "0.05";
    input.placeholder = "自定义";
    input.min = spec[name][1].min; input.max = spec[name][1].max;
    input.setAttribute("aria-label", label);
    input.onfocus = () => {
      select(); input.value = widgets[name].value; input.select();
    };
    input.onchange = () => {
      if (!input.value.trim()) { input.value = widgets[name].value; return; }
      if (!input.checkValidity()) { input.reportValidity(); return; }
      const value = Number(input.value);
      select(); update(name, value);
    };
    tile.append(input, element("span", "yton-h3-unit", name === "duration" ? "秒" : "×"));
    return input;
  }
  const promptSection = section("提示词");
  const prompt = element("textarea", "yton-h3-prompt");
  prompt.placeholder = "描述视频内容，可使用 <Picture 1>、<Video 1>、<Audio 1> 引用右侧素材";
  prompt.setAttribute("aria-label", "提示词");
  prompt.oninput = () => update("prompt", prompt.value);
  promptSection.append(prompt);

  const resolutionSection = section("输出分辨率");
  const tiersGroup = segmented("resolution", tiers, resolutionSection);
  tiersGroup.className = "yton-grid-pills yton-h3-tiers";
  for (const button of tiersGroup.children) {
    const tier = button.dataset.value;
    button.className = "yton-pill-btn";
    button.replaceChildren(element("span", "", tier), element("span", "yton-subtext", `(${multipliers[tier].toFixed(1)})`));
    button.title = "括号内为原分辨率控件的 H3 倍率";
  }
  const ratioSection = section("画面比例");
  const ratioHeading = ratioSection.firstElementChild;
  ratioHeading.classList.add("yton-h3-heading-row");
  const autoRatio = element("button", "yton-h3-auto-ratio", "自动");
  autoRatio.type = "button"; autoRatio.dataset.value = "auto";
  autoRatio.setAttribute("aria-label", "画面比例 自动");
  autoRatio.title = "按第一张启用图片匹配比例；没有图片时使用 16:9";
  autoRatio.onclick = () => update("aspect_ratio", "auto");
  ratioHeading.replaceChildren(element("span", "", "画面比例"), autoRatio);
  const ratiosGroup = segmented("aspect_ratio", ratios.filter(r => r !== "auto"), ratioSection);
  ratiosGroup.className = "yton-grid-ratios yton-h3-ratios";
  for (const button of ratiosGroup.children) {
    const ratio = button.dataset.value;
    const [w, h] = ratio.split(":").map(Number);
    const icon = element("span", "yton-ratio-icon");
    icon.style.width = `${28 * w / Math.max(w, h)}px`;
    icon.style.height = `${28 * h / Math.max(w, h)}px`;
    icon.setAttribute("aria-hidden", "true");
    button.className = "yton-ratio-card";
    button.setAttribute("aria-label", `画面比例 ${ratio}`);
    button.replaceChildren(icon, element("span", "yton-ratio-text", ratio));
  }
  const sizeInfo = element("div", "yton-h3-size-info");
  ratioSection.append(sizeInfo);

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
  const durationOptions = [5, 10, 15, "自定义"].map(value => {
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

  function dimensions(ratio = widgets.aspect_ratio.value, tier = widgets.resolution.value) {
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
    }
    const automatic = widgets.aspect_ratio.value === "auto";
    autoRatio.classList.toggle("active", automatic);
    autoRatio.setAttribute("aria-pressed", String(automatic));
    const customScale = widgets.ref_image_size.value === "自定义";
    scaleInput.parentElement.classList.toggle("active", customScale);
    if (document.activeElement !== scaleInput) scaleInput.value = customScale ? widgets.ref_scale.value : "";
    const [width, height] = dimensions();
    sizeInfo.textContent = `${width} × ${height}`;
    const custom = node.properties.ytonDurationCustom || !durationOptions.some(([v]) => v === widgets.duration.value);
    durationInput.parentElement.classList.toggle("active", Boolean(custom));
    if (document.activeElement !== durationInput) durationInput.value = custom ? widgets.duration.value : "";
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
  domWidget.element.classList.add("yton-h3-studio-shell");
  domWidget.options.canvasOnly = true;
  requestAnimationFrame(refresh);
}

app.registerExtension({ name: "yton.H3ReferenceStudio", nodeCreated(node) {
  if (node.comfyClass === "YtonH3ReferenceStudio") setupStudio(node);
} });
