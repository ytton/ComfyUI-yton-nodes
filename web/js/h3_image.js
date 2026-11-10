import { app } from "../../../scripts/app.js";
import { mountNodePanel } from "./node_panel.js";
import { setupMediaLoaderNode } from "./media_loader_panel.js";
import { availableModels, button, element, GEAR, optimizerRequest, settingsEvents } from "./prompt_optimizer_api.js";
import { openOptimizerSettings } from "./prompt_optimizer_settings.js";

const stylesheet = document.createElement("link");
stylesheet.rel = "stylesheet";
stylesheet.href = new URL("../css/h3_image.css", import.meta.url).href;
document.head.append(stylesheet);

const PRESETS = [4, 6, 8, 10, 12, 16, 20];
const RATIOS = ["auto", "1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"];
const IMAGE_CATEGORY = {
  kind: "image", label: "参考图片", count: 16, accept: "image/png,image/jpeg,image/webp,image/heic,image/heif",
  icon: '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1"/><path d="m3 17 6-6 4 4 3-3 5 5"/>',
};

function dimensions(mp, aspectRatio) {
  if (aspectRatio === "auto") return null;
  const [horizontal, vertical] = aspectRatio.split(":").map(Number);
  const ratio = horizontal / vertical;
  const area = mp * 1_000_000;
  let width = Math.round(Math.sqrt(area * ratio) / 8) * 8;
  let height = Math.round(Math.sqrt(area / ratio) / 8) * 8;
  if (width * height > 20_000_000) {
    if (width >= height) width -= 8;
    else height -= 8;
  }
  return [width, height];
}

function resolutionLabel(mp, ratio) {
  const size = dimensions(mp, ratio);
  if (!size) return "自适应";
  if (mp === 8 && ["16:9", "9:16"].includes(ratio)) return "4K";
  const k = (Math.max(...size) / 1000).toFixed(1).replace(/\.0$/, "");
  return `${k}K`;
}

function setupH3Image(node) {
  const widgets = Object.fromEntries((node.widgets || []).map(widget => [widget.name, widget]));
  node.properties ||= {};
  let settings = { providers: [], defaultModel: "" };
  let removed = false;
  let busy = false;
  let mentionStart = -1;
  let mentionEnd = -1;
  let candidates = [];
  let selectedCandidate = 0;

  const panel = setupMediaLoaderNode(node, {
    categories: [IMAGE_CATEGORY], preserveInputs: true, fixedExpanded: true, mount: false, width: 980,
    onSlotsChanged: () => { invalidateOptimization(); renderMentions(); renderSettings(); },
  });
  panel.classList.add("yton-h3-image-panel", "yton-optimizer-panel");
  const mediaColumn = element("div", "yton-h3-media-column");
  mediaColumn.append(panel.querySelector(".yton-media-section"));
  const controlsColumn = element("div", "yton-h3-controls-column");
  panel.replaceChildren(mediaColumn, controlsColumn);

  const settingsSection = element("section", "yton-h3-settings-section");
  const resolutionHeader = element("div", "yton-h3-heading");
  const dimensionsLabel = element("span", "yton-h3-detail");
  resolutionHeader.append(element("strong", "", "分辨率"), dimensionsLabel);
  const resolutionGrid = element("div", "yton-h3-resolution-grid");
  resolutionGrid.setAttribute("role", "group");
  resolutionGrid.setAttribute("aria-label", "分辨率");
  const presetButtons = PRESETS.map(mp => {
    const item = button("", () => {
      node.properties.h3CustomResolution = false;
      write("resolution_mp", mp);
      renderSettings();
    }, "yton-h3-resolution");
    item.dataset.mp = String(mp);
    item.append(element("span", "yton-h3-k"), element("span", "yton-h3-mp", `${mp} MP${mp === 16 ? " · 推荐" : ""}`));
    resolutionGrid.append(item);
    return item;
  });
  const customCell = element("label", "yton-h3-custom");
  const customInput = element("input");
  customInput.type = "number";
  customInput.min = "4";
  customInput.max = "20";
  customInput.step = "0.1";
  customInput.placeholder = "自定义";
  customInput.setAttribute("aria-label", "自定义分辨率，单位 MP");
  customCell.append(customInput, element("span", "", "MP"));
  resolutionGrid.append(customCell);

  const ratioHeader = element("div", "yton-h3-heading");
  ratioHeader.append(element("strong", "", "画面比例"), element("span", "yton-h3-detail", "1:3–3:1"));
  const ratioGrid = element("div", "yton-h3-ratio-grid");
  ratioGrid.setAttribute("role", "group");
  ratioGrid.setAttribute("aria-label", "画面比例");
  const ratioButtons = RATIOS.map(ratio => {
    const item = button("", () => { write("aspect_ratio", ratio); renderSettings(); }, "yton-h3-ratio");
    item.dataset.ratio = ratio;
    const shape = element("span", `yton-h3-ratio-shape ratio-${ratio.replace(":", "-")}`);
    shape.setAttribute("aria-hidden", "true");
    item.append(shape, element("span", "", ratio === "auto" ? "自动" : ratio));
    ratioGrid.append(item);
    return item;
  });

  const scaleRow = element("label", "yton-h3-scale-row");
  const scaleSelect = element("select", "yton-ai-input");
  scaleSelect.setAttribute("aria-label", "参考图缩放");
  for (const [target, label] of [[0, "原尺寸"], [4, "至少 4 MP · 推荐"], [8, "至少 8 MP"], [16, "至少 16 MP"]])
    scaleSelect.add(new Option(label, String(target)));
  scaleRow.append(element("span", "", "参考图缩放"), scaleSelect);
  settingsSection.append(resolutionHeader, resolutionGrid, ratioHeader, ratioGrid, scaleRow);

  const promptSection = element("section", "yton-h3-prompt-section");
  const promptHeader = element("div", "yton-h3-prompt-header");
  const tabs = element("div", "yton-h3-tabs");
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "提示词版本");
  const originalTab = button("提示词", () => selectTab(false));
  const optimizedTab = button("优化提示词", () => selectTab(true));
  originalTab.setAttribute("role", "tab");
  optimizedTab.setAttribute("role", "tab");
  tabs.append(originalTab, optimizedTab);
  const headerActions = element("div", "yton-h3-header-actions");
  const status = element("span", "yton-ai-node-status");
  status.setAttribute("role", "status");
  const gear = button("", () => { settingsPopover.hidden = !settingsPopover.hidden; }, "yton-ai-icon");
  gear.innerHTML = GEAR;
  gear.title = "优化 Skill 与 LLM 设置";
  gear.setAttribute("aria-label", gear.title);
  const optimizeButton = button("优化", () => void optimizePrompt(), "yton-ai-primary");
  headerActions.append(status, gear, optimizeButton);
  promptHeader.append(tabs, headerActions);

  const originalPanel = element("div", "yton-h3-tab-panel");
  const referenceButton = button("@ 引用", () => renderMentions(true));
  const originalToolbar = element("div", "yton-h3-editor-toolbar");
  originalToolbar.append(referenceButton);
  const promptWrap = element("div", "yton-h3-prompt-wrap");
  const prompt = element("textarea", "yton-ai-input yton-h3-prompt");
  prompt.placeholder = "描述要生成或编辑的画面，输入 @ 引用左侧图片";
  prompt.setAttribute("aria-label", "提示词输入框");
  const mentionMenu = element("div", "yton-h3-mentions");
  mentionMenu.hidden = true;
  mentionMenu.setAttribute("role", "listbox");
  promptWrap.append(prompt, mentionMenu);
  originalPanel.append(originalToolbar, promptWrap);

  const optimizedPanel = element("div", "yton-h3-tab-panel");
  const optimizedToolbar = element("div", "yton-h3-editor-toolbar");
  optimizedToolbar.append(element("span", "yton-h3-detail", "用于实际生成"));
  const optimized = element("textarea", "yton-ai-input yton-h3-prompt");
  optimized.placeholder = "优化结果在这里显示，也可直接修改";
  optimized.setAttribute("aria-label", "优化提示词输入框");
  optimizedPanel.append(optimizedToolbar, optimized);

  const settingsPopover = element("div", "yton-h3-settings-popover");
  settingsPopover.hidden = true;
  const skillSelect = element("select", "yton-ai-input");
  skillSelect.setAttribute("aria-label", "提示词优化 Skill");
  const modelSelect = element("select", "yton-ai-input");
  modelSelect.setAttribute("aria-label", "LLM 模型");
  const providerButton = button("服务商设置", () => openOptimizerSettings());
  settingsPopover.append(
    labeledSelect("优化 Skill", skillSelect),
    labeledSelect("LLM 模型", modelSelect),
    providerButton,
  );
  promptSection.append(promptHeader, originalPanel, optimizedPanel, settingsPopover);
  controlsColumn.append(settingsSection, promptSection);

  function labeledSelect(label, control) {
    const wrapper = element("label", "yton-h3-popover-field");
    wrapper.append(element("span", "", label), control);
    return wrapper;
  }

  function write(name, value) {
    widgets[name].value = value;
    widgets[name].callback?.(value);
    node.setDirtyCanvas(true, true);
  }

  function report(message, error = false) {
    status.textContent = message;
    status.classList.toggle("yton-ai-error", error);
  }

  function invalidateOptimization() {
    write("optimized_prompt", "");
    optimized.value = "";
    report("");
  }

  function renderSettings() {
    const mp = Number(widgets.resolution_mp.value);
    const ratio = widgets.aspect_ratio.value;
    const size = dimensions(mp, ratio);
    dimensionsLabel.textContent = size ? `${mp} MP · ${size[0]} × ${size[1]}` : `${mp} MP · 按参考图比例`;
    const custom = Boolean(node.properties.h3CustomResolution) || !PRESETS.includes(mp);
    for (const item of presetButtons) {
      const value = Number(item.dataset.mp);
      item.setAttribute("aria-pressed", String(!custom && value === mp));
      item.querySelector(".yton-h3-k").textContent = resolutionLabel(value, ratio);
    }
    customCell.classList.toggle("is-selected", custom);
    if (document.activeElement !== customInput) customInput.value = custom ? String(mp) : "";
    for (const item of ratioButtons) item.setAttribute("aria-pressed", String(item.dataset.ratio === ratio));
    scaleSelect.value = String(widgets.reference_target_mp.value);
  }

  function selectTab(showOptimized) {
    originalTab.setAttribute("aria-selected", String(!showOptimized));
    optimizedTab.setAttribute("aria-selected", String(showOptimized));
    originalPanel.hidden = showOptimized;
    optimizedPanel.hidden = !showOptimized;
    mentionMenu.hidden = true;
  }

  function filledSlots() {
    return Array.from({ length: 16 }, (_, index) => index + 1).filter(number =>
      widgets[`image_${number}`].value && !widgets[`disable_image_${number}`].value);
  }

  function renderMentions(showAll = false) {
    const before = prompt.value.slice(0, prompt.selectionStart);
    const match = showAll ? null : before.match(/@(\d{0,2})$/);
    mentionStart = showAll ? prompt.selectionStart : match ? prompt.selectionStart - match[0].length : -1;
    mentionEnd = prompt.selectionEnd;
    const prefix = match?.[1] || "";
    candidates = mentionStart < 0 ? [] : filledSlots().filter(number => String(number).startsWith(prefix));
    selectedCandidate = 0;
    mentionMenu.replaceChildren(...candidates.map((number, index) => {
      const filename = widgets[`image_${number}`].value.split("/").pop();
      const item = button(`@${number} · ${filename}`, () => insertMention(number));
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", String(index === selectedCandidate));
      item.onpointerdown = event => event.preventDefault();
      return item;
    }));
    mentionMenu.hidden = !candidates.length;
    if (showAll) prompt.focus();
  }

  function insertMention(number) {
    if (mentionStart < 0) return;
    const caret = mentionStart + String(number).length + 1;
    prompt.value = `${prompt.value.slice(0, mentionStart)}@${number}${prompt.value.slice(mentionEnd)}`;
    prompt.focus();
    prompt.setSelectionRange(caret, caret);
    mentionMenu.hidden = true;
    write("prompt", prompt.value);
    invalidateOptimization();
  }

  function updateModels() {
    const models = availableModels(settings);
    modelSelect.replaceChildren(new Option("使用共享默认模型", ""),
      ...models.map(model => new Option(model.label, model.value)));
    modelSelect.value = widgets.model_ref.value;
  }

  async function loadSkills() {
    try {
      const data = await optimizerRequest("skills");
      if (removed) return;
      skillSelect.replaceChildren(...data.skills.map(name => new Option(name === "h3-image" ? "H3 Image 提示词优化" : name, name)));
      skillSelect.value = widgets.skill_name.value;
    } catch (error) {
      if (!removed) report(error.message, true);
    }
  }

  function optimizationSnapshot() {
    const data = {
      prompt: prompt.value, optimized_prompt: optimized.value,
      model_ref: widgets.model_ref.value, skill_name: widgets.skill_name.value,
      reference_target_mp: Number(widgets.reference_target_mp.value),
    };
    for (let number = 1; number <= 16; number++) {
      data[`image_${number}`] = widgets[`image_${number}`].value;
      data[`disable_image_${number}`] = widgets[`disable_image_${number}`].value;
    }
    return data;
  }

  async function optimizePrompt() {
    if (busy) return;
    busy = true;
    optimizeButton.disabled = true;
    report("优化中…");
    const payload = optimizationSnapshot();
    const snapshot = JSON.stringify(payload);
    try {
      const result = await optimizerRequest("h3-image", payload);
      if (!removed && snapshot === JSON.stringify(optimizationSnapshot())) {
        write("optimized_prompt", result.text);
        optimized.value = result.text;
        report("已优化");
        selectTab(true);
      } else if (!removed) report("内容已变化，请重新优化");
    } catch (error) {
      if (!removed) report(error.message, true);
    } finally {
      busy = false;
      optimizeButton.disabled = false;
    }
  }

  customInput.addEventListener("focus", () => {
    node.properties.h3CustomResolution = true;
    if (!customInput.value) customInput.value = String(widgets.resolution_mp.value);
    customInput.select();
    renderSettings();
  });
  customInput.addEventListener("input", () => {
    const mp = Number(customInput.value);
    if (customInput.value && mp >= 4 && mp <= 20) { write("resolution_mp", mp); report(""); }
    else report("自定义分辨率为 4–20 MP", true);
    renderSettings();
  });
  customInput.addEventListener("change", () => {
    const mp = Math.min(20, Math.max(4, Number(customInput.value) || 16));
    customInput.value = String(mp);
    write("resolution_mp", mp);
    report("");
    renderSettings();
  });
  scaleSelect.addEventListener("change", () => {
    write("reference_target_mp", Number(scaleSelect.value));
    invalidateOptimization();
  });
  prompt.addEventListener("input", () => {
    write("prompt", prompt.value);
    invalidateOptimization();
    renderMentions();
  });
  prompt.addEventListener("click", () => renderMentions());
  prompt.addEventListener("keydown", event => {
    if (mentionMenu.hidden) return;
    if (event.key === "Escape") { mentionMenu.hidden = true; return; }
    if (["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      selectedCandidate = (selectedCandidate + (event.key === "ArrowDown" ? 1 : -1) + candidates.length) % candidates.length;
      [...mentionMenu.children].forEach((item, index) => item.setAttribute("aria-selected", String(index === selectedCandidate)));
    }
    if (event.key === "Enter") { event.preventDefault(); insertMention(candidates[selectedCandidate]); }
  });
  optimized.addEventListener("input", () => write("optimized_prompt", optimized.value));
  skillSelect.addEventListener("change", () => { write("skill_name", skillSelect.value); invalidateOptimization(); });
  modelSelect.addEventListener("change", () => { write("model_ref", modelSelect.value); invalidateOptimization(); });
  panel.addEventListener("pointerdown", event => event.stopPropagation());
  panel.addEventListener("keydown", event => {
    event.stopPropagation();
    if (event.key === "Escape") settingsPopover.hidden = true;
  });

  function sync() {
    prompt.value = widgets.prompt.value || "";
    optimized.value = widgets.optimized_prompt.value || "";
    prompt.disabled = node.inputs?.some(input => input.name === "prompt" && input.link != null) || false;
    renderSettings();
    updateModels();
    selectTab(false);
  }
  const onConfigure = node.onConfigure;
  node.onConfigure = function () { const result = onConfigure?.apply(this, arguments); sync(); return result; };
  const onConnectionsChange = node.onConnectionsChange;
  node.onConnectionsChange = function () { const result = onConnectionsChange?.apply(this, arguments); sync(); return result; };
  const settingsChanged = event => { settings = event.detail; updateModels(); };
  settingsEvents.addEventListener("change", settingsChanged);
  const onRemoved = node.onRemoved;
  node.onRemoved = function () {
    removed = true;
    settingsEvents.removeEventListener("change", settingsChanged);
    return onRemoved?.apply(this, arguments);
  };
  sync();
  void loadSkills();
  optimizerRequest("settings").then(data => { if (!removed) { settings = data; updateModels(); } })
    .catch(error => { if (!removed) report(error.message, true); });
  mountNodePanel(node, "h3_image_ui", panel, 760, 590, { fitHeight: true });
}

app.registerExtension({
  name: "yton.h3_image",
  nodeCreated(node) { if (node.comfyClass === "YtonH3ImageConfig") setupH3Image(node); },
});
