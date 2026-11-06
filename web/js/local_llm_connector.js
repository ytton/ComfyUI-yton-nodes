import { button, el, hideWidget, request } from "./replacement_common.js";
import { followNodeColours, mountNodePanel } from "./node_panel.js";
import { openLlamaSettings } from "./llama_optimizer_settings.js";
import { attachMenuPopover } from "./menu_popover.js";

export function setupLocalLLMConnector(node) {
  const widgets = Object.fromEntries(node.widgets.map(widget => [widget.name, widget]));
  hideWidget(widgets.model_name);
  hideWidget(widgets.options_json);
  const root = el("div", "yton-replacement-panel yton-optimizer-panel yr-connector yr-local-connector");
  const menu = el("details", "yton-ai-model-menu");
  const label = el("summary");
  label.setAttribute("aria-label", "本地 GGUF 模型");
  const choices = el("div", "yton-ai-model-options");
  menu.append(label, choices);
  const closeMenu = attachMenuPopover(menu, choices);
  const row = el("div", "yton-ai-model-row");
  const refresh = button("↻", () => void loadModels(), "刷新本地 GGUF 模型");
  const gear = button("⚙", () => {
    if (!catalogue) { status.textContent = "模型列表尚未就绪，请先刷新。"; return; }
    closeMenu();
    openLlamaSettings(widgets.options_json.value, catalogue, value => {
      widgets.options_json.value = value;
      node.setDirtyCanvas(true, true);
    });
  }, "本地推理设置");
  row.append(menu, refresh, gear);
  const status = el("div", "yton-ai-node-status");
  status.setAttribute("role", "status");
  root.append(el("span", "yr-label", "GGUF 模型"), row, status);
  let catalogue;
  let removed = false;
  function sync() {
    label.textContent = widgets.model_name.value || "请选择本地 GGUF 模型";
    label.title = widgets.model_name.value || "模型目录：ComfyUI/models/LLM";
    choices.replaceChildren(...(catalogue?.models || []).map(name => {
      const choice = button(name, () => {
        widgets.model_name.value = name;
        node.setDirtyCanvas(true, true);
        closeMenu();
        sync();
      });
      choice.setAttribute("aria-pressed", String(name === widgets.model_name.value));
      return choice;
    }));
  }
  async function loadModels() {
    refresh.disabled = true;
    status.textContent = "";
    try {
      const data = await request("prompt-optimizer/llama");
      if (removed) return;
      catalogue = data;
      sync();
      if (!catalogue.models.length) status.textContent = "请将 GGUF 模型放入 ComfyUI/models/LLM 后刷新。";
    } catch (error) { if (!removed) status.textContent = error.message; }
    finally { refresh.disabled = false; }
  }
  root.addEventListener("pointerdown", event => event.stopPropagation());
  root.addEventListener("keydown", event => event.stopPropagation());
  const configured = node.onConfigure;
  node.onConfigure = function () { configured?.apply(this, arguments); sync(); };
  const dispose = node.onRemoved;
  node.onRemoved = function () { removed = true; closeMenu(); return dispose?.apply(this, arguments); };
  followNodeColours(node, root);
  mountNodePanel(node, "本地 LLM", root, 330, 76, { fitHeight: true });
  root.parentElement.style.overflow = "hidden";
  sync();
  void loadModels();
}
