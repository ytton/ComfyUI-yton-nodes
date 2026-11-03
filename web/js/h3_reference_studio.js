import { app } from "../../../scripts/app.js";
import { mountNodePanel, followNodeColours } from "./node_panel.js";
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
  // ComfyUI infers rounding from the step; the custom duration accepts any decimal.
  widgets.duration.options.round = false;
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
    input.type = "number"; input.step = name === "duration" ? "any" : "0.05";
    input.inputMode = "decimal";
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
  followNodeColours(node, panel);
  node.setSize([1080, node.size[1]]);
  const domWidget = mountNodePanel(node, "h3_reference_studio_ui", panel, 860, 560, { fitHeight: true });
  domWidget.element.classList.add("yton-h3-studio-shell");
  domWidget.options.canvasOnly = true;
  requestAnimationFrame(refresh);
}

function setupVideoConfig(node) {
  const widgets = Object.fromEntries(node.widgets.map(widget => [widget.name, widget]));
  widgets.duration.options.round = false;
  const spec = node.constructor.nodeData.input.required;
  const presets = spec.resolution[1].yton_presets;
  const multipliers = spec.resolution[1].yton_h3_multipliers;
  const ratios = spec.aspect_ratio[1].options.filter(value => value !== "auto");
  for (const widget of node.widgets) {
    widget.type = "hidden"; widget.hidden = true;
    widget.computeSize = () => [0, 0];
    widget.computeLayoutSize = () => ({ minWidth: 0, minHeight: 0, maxHeight: 0 });
    widget.draw = () => {};
    widget.options.hidden = true;
    if (widget.element) widget.element.style.display = "none";
  }

  const panel = element("div", "yton-panel yton-h3-config");
  const controls = element("div", "yton-h3-controls");
  const promptColumn = element("section", "yton-h3-config-prompt");
  const promptHeader = element("div", "yton-h3-heading yton-h3-heading-row");
  const optimizeButton = element("button", "yton-h3-auto-ratio", "✦ 优化");
  optimizeButton.type = "button";
  optimizeButton.title = "使用连接的 LLM 和参考素材优化提示词；只执行此配置器及其上游输入";
  const promptStatus = element("div", "yton-h3-size-info");
  promptHeader.append(element("span", "", "提示词"), optimizeButton);
  panel.append(controls, promptColumn);
  const groups = [];
  let refreshing = false;
  let optimizationPending = false;

  function update(name, value) {
    node.graph?.beforeChange();
    widgets[name].value = value;
    widgets[name].callback?.(value);
    node.graph?.afterChange();
    node._h3VideoConfig = null;
    refresh();
  }
  function section(title) {
    const root = element("section", "yton-h3-section");
    root.append(element("div", "yton-h3-heading", title));
    controls.append(root);
    return root;
  }
  function segmented(name, options, host, label = value => value) {
    const group = element("div", "yton-h3-segments");
    group.setAttribute("role", "group"); group.setAttribute("aria-label", name);
    const buttons = options.map(value => {
      const control = element("button", "yton-h3-choice", label(value));
      control.type = "button"; control.dataset.value = value;
      control.onclick = () => update(name, value);
      group.append(control);
      return [value, control];
    });
    groups.push([name, buttons]); host.append(group);
    return group;
  }
  function customChoice(group, name, label, select) {
    const button = group.querySelector('[data-value="自定义"]');
    const tile = element("div", "yton-h3-custom-choice");
    button.replaceWith(tile);
    const input = element("input", "");
    input.type = "number"; input.step = name === "duration" ? "any" : "0.05";
    input.inputMode = "decimal"; input.placeholder = "自定义";
    input.min = spec[name][1].min; input.max = spec[name][1].max;
    input.setAttribute("aria-label", label);
    input.onfocus = () => { select(); input.value = widgets[name].value; input.select(); };
    input.onchange = () => {
      if (!input.value.trim()) { input.value = widgets[name].value; return; }
      if (!input.checkValidity()) { input.reportValidity(); return; }
      select(); update(name, Number(input.value));
    };
    tile.append(input, element("span", "yton-h3-unit", name === "duration" ? "秒" : "×"));
    return input;
  }

  const prompt = element("textarea", "yton-h3-prompt");
  prompt.placeholder = "描述视频内容，可使用 <Picture 1>、<Video 1>、<Audio 1> 引用素材";
  prompt.setAttribute("aria-label", "提示词");
  prompt.oninput = () => { promptStatus.textContent = ""; update("prompt", prompt.value); };
  promptColumn.append(promptHeader, prompt, promptStatus);

  const resolutionSection = section("输出分辨率");
  const resolutionGroup = segmented("resolution", spec.resolution[1].options, resolutionSection);
  resolutionGroup.className = "yton-grid-pills yton-h3-tiers";
  for (const button of resolutionGroup.children) {
    const resolution = button.dataset.value;
    button.className = "yton-pill-btn";
    button.replaceChildren(element("span", "", resolution), element("span", "yton-subtext", `(${multipliers[resolution].toFixed(1)})`));
  }

  const ratioSection = section("画面比例");
  const ratioHeading = ratioSection.firstElementChild;
  ratioHeading.classList.add("yton-h3-heading-row");
  const autoRatio = element("button", "yton-h3-auto-ratio", "自动");
  autoRatio.type = "button"; autoRatio.dataset.value = "auto";
  autoRatio.setAttribute("aria-label", "画面比例 自动");
  autoRatio.title = "按连接的 IMAGE 输入匹配比例；未连接时使用 16:9";
  autoRatio.onclick = () => update("aspect_ratio", "auto");
  ratioHeading.replaceChildren(element("span", "", "画面比例"), autoRatio);
  const ratioGroup = segmented("aspect_ratio", ratios, ratioSection);
  ratioGroup.className = "yton-grid-ratios yton-h3-ratios";
  for (const button of ratioGroup.children) {
    const ratio = button.dataset.value;
    const [width, height] = ratio.split(":").map(Number);
    const icon = element("span", "yton-ratio-icon");
    icon.style.width = `${28 * width / Math.max(width, height)}px`;
    icon.style.height = `${28 * height / Math.max(width, height)}px`;
    icon.setAttribute("aria-hidden", "true");
    button.className = "yton-ratio-card";
    button.setAttribute("aria-label", `画面比例 ${ratio}`);
    button.replaceChildren(icon, element("span", "yton-ratio-text", ratio));
  }
  const sizeInfo = element("div", "yton-h3-size-info");
  ratioSection.append(sizeInfo);

  const refSection = section("参考图尺寸");
  refSection.title = "match：按输出像素面积缩小参考图；max：使用原生最大参考尺寸；自定义：输出倍率供下游参考图缩放使用。";
  const refGroup = segmented("ref_image_size", ["max", "match", "自定义"], refSection);
  refGroup.classList.add("yton-h3-ref-size");
  const scaleInput = customChoice(refGroup, "ref_scale", "参考图缩放比例", () => {
    if (widgets.ref_image_size.value !== "自定义") update("ref_image_size", "自定义");
  });

  const durationSection = section("视频时长");
  const durationGroup = element("div", "yton-h3-segments yton-h3-durations");
  durationSection.append(durationGroup);
  const durationOptions = [5, 10, 15, "自定义"].map(value => {
    const button = element("button", "yton-h3-choice", value === "自定义" ? value : `${value} 秒`);
    button.type = "button"; button.dataset.value = value;
    button.onclick = () => {
      node.properties.ytonDurationCustom = value === "自定义";
      if (value !== "自定义") update("duration", value);
      else { node.graph?.change(); refresh(); }
    };
    durationGroup.append(button); return [value, button];
  });
  const durationInput = customChoice(durationGroup, "duration", "自定义秒数", () => {
    node.properties.ytonDurationCustom = true; refresh();
  });
  const timeInfo = element("div", "yton-h3-size-info");
  durationSection.append(timeInfo);

  function dimensions() {
    const ratio = widgets.aspect_ratio.value === "auto" ? "16:9" : widgets.aspect_ratio.value;
    return presets[`${ratio}|${widgets.resolution.value}`];
  }
  function refresh() {
    if (refreshing || !panel.isConnected) return;
    refreshing = true;
    if (document.activeElement !== prompt) prompt.value = widgets.prompt.value;
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
    const output = node._h3VideoConfig;
    sizeInfo.textContent = automatic && output ? `${output.width} × ${output.height} · ${output.aspect_ratio}` :
      automatic ? "按连接图片匹配比例" : `${width} × ${height}`;
    const customDuration = node.properties.ytonDurationCustom || !durationOptions.some(([value]) => value === widgets.duration.value);
    durationInput.parentElement.classList.toggle("active", Boolean(customDuration));
    if (document.activeElement !== durationInput) durationInput.value = customDuration ? widgets.duration.value : "";
    for (const [value, button] of durationOptions) {
      const active = customDuration ? value === "自定义" : value === widgets.duration.value;
      button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active));
    }
    const frames = Math.ceil((Math.max(5, Math.ceil(widgets.duration.value * 24)) - 5) / 17) * 17 + 5;
    const actualFrames = output?.frames || frames;
    timeInfo.textContent = `${actualFrames} 帧 · 实际 ${((output?.seconds ?? actualFrames / 24)).toFixed(2)} 秒 · 24 fps`;
    node.setDirtyCanvas(true, true);
    refreshing = false;
  }
  const configure = node.onConfigure;
  node.onConfigure = function () { const result = configure?.apply(this, arguments); requestAnimationFrame(refresh); return result; };
  const connections = node.onConnectionsChange;
  node.onConnectionsChange = function () {
    const result = connections?.apply(this, arguments);
    node._h3VideoConfig = null;
    promptStatus.textContent = "";
    refresh();
    return result;
  };
  for (const widget of Object.values(widgets)) {
    const callback = widget.callback;
    widget.callback = function () { const result = callback?.apply(this, arguments); refresh(); return result; };
  }
  const executed = node.onExecuted;
  node.onExecuted = function (data) {
    executed?.apply(this, arguments);
    optimizationPending = false;
    optimizeButton.disabled = false;
    if (data.h3_video_config?.[0]) node._h3VideoConfig = data.h3_video_config[0];
    const output = data.h3_video_prompt?.[0];
    if (output) {
      promptStatus.textContent = `${output.image_count} 张图片 · ${output.video_count} 段视频 · ${output.audio_count} 段音频${output.optimized ? " · 已优化" : ""}`;
      if (output.optimized) {
        widgets.prompt.value = output.text;
        widgets.optimize_prompt.value = false;
        node.graph?.change();
      }
    }
    refresh();
  };
  const executionError = node.onExecutionError;
  node.onExecutionError = function () {
    const result = executionError?.apply(this, arguments);
    if (optimizationPending) {
      optimizationPending = false;
      optimizeButton.disabled = false;
      widgets.optimize_prompt.value = false;
      promptStatus.textContent = "优化失败，请查看节点执行错误";
    }
    return result;
  };
  optimizeButton.onclick = async () => {
    if (optimizationPending) return;
    const llm = node.inputs.find(input => input.name === "llm");
    if (!llm?.link) {
      promptStatus.textContent = "连接 LLM 后即可优化提示词";
      return;
    }
    optimizationPending = true;
    optimizeButton.disabled = true;
    widgets.optimize_prompt.value = true;
    node.graph?.change();
    promptStatus.textContent = "正在优化提示词…仅执行此配置器及其上游输入";
    try {
      const queued = await app.queuePrompt(0, 1, [node.id]);
      if (queued?.node_errors) throw new Error("工作流输入校验失败，请查看节点执行错误");
      if (optimizationPending) promptStatus.textContent = "已加入队列，等待优化完成";
    } catch (error) {
      optimizationPending = false;
      optimizeButton.disabled = false;
      widgets.optimize_prompt.value = false;
      node.graph?.change();
      promptStatus.textContent = error.message || "无法提交提示词优化任务";
    }
  };
  followNodeColours(node, panel);
  node.setSize([1060, node.size[1]]);
  const domWidget = mountNodePanel(node, "h3_video_config_ui", panel, 980, 680, { fitHeight: true });
  domWidget.element.classList.add("yton-h3-config-shell");
  domWidget.options.canvasOnly = true;
  requestAnimationFrame(refresh);
}

app.registerExtension({ name: "yton.H3ReferenceStudio", nodeCreated(node) {
  if (node.comfyClass === "YtonH3ReferenceStudio") setupStudio(node);
  if (node.comfyClass === "YtonH3VideoConfig") setupVideoConfig(node);
} });
