import { app } from "../../../scripts/app.js";
import { mountNodePanel } from "./node_panel.js";
import { availableModels, button, element, field, GEAR, optimizerRequest, settingsEvents } from "./prompt_optimizer_api.js";
import { openOptimizerSettings } from "./prompt_optimizer_settings.js";
import { openLlamaSettings } from "./llama_optimizer_settings.js";

const stylesheet = document.createElement("link");
stylesheet.rel = "stylesheet";
stylesheet.href = new URL("../css/prompt_optimizer.css", import.meta.url).href;
document.head.appendChild(stylesheet);

function setupOptimizer(node) {
  const local = node.comfyClass === "YtonLlamaCppOptimizer";
  const widgets = Object.fromEntries(node.widgets.map(widget => [widget.name, widget]));
  for (const widget of Object.values(widgets)) {
    widget.type = "hidden";
    widget.hidden = true;
    widget.computeSize = () => [0, 0];
    widget.computeLayoutSize = () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
    widget.draw = () => {};
    if (widget.options) widget.options.hidden = true;
    if (widget.element) widget.element.style.display = "none";
  }
  const panel = element("div", "yton-optimizer-panel");
  const enabled = element("input");
  enabled.type = "checkbox";
  const enableField = element("label", "yton-ai-check");
  enableField.title = "关闭后直接使用用户提示词，跳过增强处理。";
  enableField.append(enabled, element("span", "", "启用提示词增强"));
  const prompt = element("textarea", "yton-ai-input yton-ai-prompt");
  prompt.placeholder = "描述主体、场景、动作和希望保留的细节…";
  const rules = element("textarea", "yton-ai-input yton-ai-rules");
  rules.setAttribute("aria-label", "系统提示词");
  const rulesSection = element("details", "yton-ai-rules-section");
  rulesSection.append(element("summary", "", "系统提示词"), rules);
  const skillMenu = element("details", "yton-ai-model-menu yton-ai-skill-menu");
  const skillLabel = element("summary", "", "不使用 Skill");
  const skillOptions = element("div", "yton-ai-model-options");
  skillMenu.append(skillLabel, skillOptions);
  const refreshSkills = button("↻", () => void loadSkills(), "yton-ai-icon");
  refreshSkills.title = "刷新 Skill 列表";
  refreshSkills.setAttribute("aria-label", refreshSkills.title);
  const skillRow = element("div", "yton-ai-inline yton-ai-skill-row");
  skillRow.append(skillMenu, refreshSkills);
  const skillField = element("div", "yton-ai-field");
  skillField.append(element("span", "", "Skill"), skillRow);
  const modelMenu = element("details", "yton-ai-model-menu");
  const modelLabel = element("summary", "", "使用默认模型");
  const modelOptions = element("div", "yton-ai-model-options");
  modelMenu.append(modelLabel, modelOptions);
  const modelRow = element("div", "yton-ai-inline yton-ai-model-row");
  modelRow.append(modelMenu);
  if (local) {
    const refresh = button("↻", () => void loadLocalModels(), "yton-ai-icon");
    refresh.title = "刷新本地 GGUF 模型";
    refresh.setAttribute("aria-label", refresh.title);
    modelRow.append(refresh);
  }
  const status = element("div", "yton-ai-node-status");
  status.setAttribute("role", "status");
  const footer = element("div", "yton-ai-node-footer");
  const gear = button("", () => {
    if (!local) return openOptimizerSettings();
    if (!catalogue) return report("本地模型列表未就绪，请点击模型旁的刷新按钮。", true);
    openLlamaSettings(widgets.options_json.value, catalogue, value => { write("options_json", value); invalidate(); });
  }, "yton-ai-icon yton-ai-settings");
  gear.innerHTML = GEAR;
  gear.title = local ? "llama.cpp 高级设置（当前节点）" : "服务商与模型设置（所有优化器共用）";
  gear.setAttribute("aria-label", gear.title);
  footer.append(gear);
  panel.append(enableField, field("用户提示词", prompt), rulesSection, skillField, modelRow, status, footer);
  panel.dataset.runtime = local ? "llama" : "openai";
  mountNodePanel(node, "prompt_optimizer_ui", panel, 340, 290);
  let settings = { providers: [], defaultModel: "" };
  let skills = null;
  let removed = false;
  let catalogue = null;

  function write(name, value) {
    widgets[name].value = value;
    node.setDirtyCanvas(true, true);
  }
  function report(message, error = false) {
    status.textContent = message;
    status.classList.toggle("yton-ai-error", error);
  }
  function invalidate() {
    report("");
  }
  prompt.addEventListener("input", () => { write("prompt", prompt.value); invalidate(); });
  rules.addEventListener("input", () => { write("rules", rules.value); invalidate(); });
  enabled.addEventListener("change", () => { write("enabled", enabled.checked); invalidate(); });
  panel.addEventListener("keydown", event => event.stopPropagation());
  // Text selection and controls must not start a canvas pan/drag.
  panel.addEventListener("pointerdown", event => event.stopPropagation());

  function updateModels() {
    if (local) {
      const selection = widgets.model_name.value;
      modelLabel.textContent = selection || "请选择本地 GGUF 模型";
      modelLabel.title = selection || "模型目录：ComfyUI/models/LLM";
      modelOptions.replaceChildren(...(catalogue?.models || []).map(name => button(name, () => {
        write("model_name", name); invalidate(); updateModels(); modelMenu.open = false;
      })));
      return;
    }
    const models = availableModels(settings);
    const reference = widgets.model_ref.value;
    const selected = models.find(model => model.value === reference);
    const defaultModel = models.find(model => model.value === settings.defaultModel);
    modelLabel.textContent = reference ? selected?.label || "所选模型不可用" : `默认：${defaultModel?.label || "请先配置模型"}`;
    modelLabel.title = modelLabel.textContent;
    modelOptions.replaceChildren(...[{ value: "", label: "使用共享默认模型" }, ...models].map(model =>
      button(model.label, () => { write("model_ref", model.value); invalidate(); updateModels(); modelMenu.open = false; })));
  }
  async function loadLocalModels() {
    try {
      const data = await optimizerRequest("llama");
      if (!removed) { catalogue = data; updateModels(); report(data.models.length ? "" : "请将 GGUF 放入 ComfyUI/models/LLM，然后刷新。", !data.models.length); }
    } catch (error) { if (!removed) report(error.message, true); }
  }
  function updateSkills() {
    const selected = widgets.skill_name.value;
    skillLabel.textContent = selected ? skills === null || skills.includes(selected) ? selected : `${selected} · 不可用` : "不使用 Skill";
    skillLabel.title = "执行时读取 SKILL.md 和目录内文本参考文件，一次请求发送。";
    if (skills === null) return;
    widgets.skill_name.options.values = ["", ...skills];
    skillOptions.replaceChildren(...["", ...skills].map(name => button(name || "不使用 Skill", () => {
      write("skill_name", name); invalidate(); updateSkills(); skillMenu.open = false;
    })));
  }
  async function loadSkills() {
    refreshSkills.disabled = true;
    try {
      const data = await optimizerRequest("skills");
      if (!removed) { skills = data.skills; updateSkills(); }
    } catch (error) { if (!removed) report(error.message, true); }
    finally { refreshSkills.disabled = false; }
  }
  function sync() {
    enabled.checked = widgets.enabled.value;
    prompt.value = widgets.prompt.value || "";
    rules.value = widgets.rules.value || "";
    for (const name of ["prompt", "rules"]) {
      const input = node.inputs.find(input => input.name === name) || node.addInput(name, "STRING");
      // The canvas sockets stay visible independently of the hidden native widgets.
      delete input.widget;
    }
    const linked = name => node.inputs?.some(input => input.name === name && input.link != null);
    const labels = { prompt: "用户提示词", rules: "系统提示词", image: "image · 图片列表", audio: "audio · 音频列表", video: "video · 视频列表" };
    for (const input of node.inputs || []) if (labels[input.name]) input.label = labels[input.name];
    prompt.disabled = linked("prompt");
    rules.disabled = linked("rules");
    updateModels();
    updateSkills();
  }
  const onConfigure = node.onConfigure;
  node.onConfigure = function () { const value = onConfigure?.apply(this, arguments); sync(); return value; };
  const onConnectionsChange = node.onConnectionsChange;
  node.onConnectionsChange = function () { onConnectionsChange?.apply(this, arguments); sync(); };
  const onExecuted = node.onExecuted;
  node.onExecuted = function (message) {
    onExecuted?.apply(this, arguments);
    if (message.optimized_prompt?.[0] !== undefined) {
      report(widgets.enabled.value ? "优化完成" : "原提示词已直通"); sync();
    }
  };
  const changed = event => { settings = event.detail; invalidate(); updateModels(); };
  if (!local) settingsEvents.addEventListener("change", changed);
  const onRemoved = node.onRemoved;
  node.onRemoved = function () { removed = true; settingsEvents.removeEventListener("change", changed); return onRemoved?.apply(this, arguments); };
  sync();
  void loadSkills();
  if (local) void loadLocalModels();
  else optimizerRequest("settings").then(data => { if (!removed) { settings = data; updateModels(); } }).catch(error => report(error.message, true));
}

app.registerExtension({
  name: "yton.prompt_optimizer",
  nodeCreated(node) { if (["YtonPromptOptimizer", "YtonLlamaCppOptimizer"].includes(node.comfyClass)) setupOptimizer(node); },
});
