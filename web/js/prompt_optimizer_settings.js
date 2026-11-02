import { availableModels, button, element, field, modelReference, optimizerRequest, settingsEvents } from "./prompt_optimizer_api.js";

let activeDialog;

export async function openOptimizerSettings(request = optimizerRequest) {
  if (activeDialog) { activeDialog.focus(); return; }
  const dialog = element("dialog", "yton-ai-dialog");
  activeDialog = dialog;
  const heading = element("header", "yton-ai-dialog-header");
  const title = element("h2", "", "服务商与模型");
  title.id = `yton-ai-title-${crypto.randomUUID()}`;
  dialog.setAttribute("aria-labelledby", title.id);
  const close = button("×", () => dialog.close(), "yton-ai-icon");
  close.title = "关闭";
  close.setAttribute("aria-label", "关闭");
  heading.append(title, close);
  const content = element("div", "yton-ai-dialog-body");
  const sidebar = element("aside", "yton-ai-providers");
  const providerList = element("div", "yton-ai-provider-list");
  const editor = element("div", "yton-ai-editor");
  const status = element("div", "yton-ai-status", "正在读取配置…");
  status.setAttribute("role", "status");
  const footer = element("footer", "yton-ai-dialog-footer");
  const save = button("保存", saveSettings, "yton-ai-primary");
  save.disabled = true;
  sidebar.append(providerList, button("＋ 添加服务商", addProvider));
  content.append(sidebar, editor);
  footer.append(status, button("取消", () => dialog.close()), save);
  dialog.append(heading, content, footer);
  // Keep canvas shortcuts and pointer gestures outside this modal's controls.
  dialog.addEventListener("keydown", event => event.stopPropagation());
  dialog.addEventListener("close", () => { dialog.remove(); activeDialog = null; }, { once: true });
  document.body.appendChild(dialog);
  dialog.showModal();

  let settings = { providers: [], defaultModel: "" };
  let selectedId;
  let busy = false;

  function report(message, error = false) {
    status.textContent = message;
    status.classList.toggle("yton-ai-error", error);
  }

  function normalizeDefault() {
    const models = availableModels(settings);
    if (!models.some(model => model.value === settings.defaultModel)) settings.defaultModel = models[0]?.value || "";
  }

  function renderProviders() {
    providerList.replaceChildren(...settings.providers.map(provider => {
      const item = button("", () => { selectedId = provider.id; render(); }, "yton-ai-provider");
      item.classList.toggle("is-active", provider.id === selectedId);
      item.append(element("strong", "", provider.name), element("small", "", provider.enabled ? `${provider.models.length} 个模型` : "已停用"));
      return item;
    }));
  }

  function addProvider() {
    if (busy) return;
    const provider = { id: crypto.randomUUID(), name: "新服务商", baseUrl: "https://api.openai.com/v1", apiKey: "", models: [], enabled: true };
    settings.providers.push(provider);
    selectedId = provider.id;
    report("");
    render();
  }

  function input(value, placeholder, onInput, type = "text") {
    const control = element("input", "yton-ai-input");
    control.type = type;
    control.value = value;
    control.placeholder = placeholder;
    control.autocomplete = "off";
    control.addEventListener("input", () => onInput(control.value));
    return control;
  }

  function render() {
    renderProviders();
    editor.replaceChildren();
    const provider = settings.providers.find(item => item.id === selectedId);
    if (!provider) { editor.append(element("div", "yton-ai-empty", "添加一个服务商，配置服务地址和模型。")); return; }
    const name = input(provider.name, "例如：我的 AI 服务", value => { provider.name = value; renderProviders(); });
    const baseUrl = input(provider.baseUrl, "https://example.com/v1", value => { provider.baseUrl = value; });
    baseUrl.title = "填写 API 基础地址（含服务商要求的 /v1 等前缀），将调用 /chat/completions 和 /models。";
    const key = input(provider.apiKey || "", provider.apiKeyConfigured && !provider.clearApiKey ? "已保存；留空保留现有密钥" : "输入 API Key", value => {
      provider.apiKey = value;
      if (value) provider.clearApiKey = false;
    }, "password");
    const keyRow = element("div", "yton-ai-inline");
    keyRow.append(key, button("清除", () => {
      provider.apiKey = "";
      provider.clearApiKey = true;
      key.value = "";
      key.placeholder = "保存后清除密钥";
    }));
    const enabled = input("", "", () => { provider.enabled = enabled.checked; normalizeDefault(); renderProviders(); renderModels(); }, "checkbox");
    enabled.checked = provider.enabled;
    const enabledLabel = element("label", "yton-ai-check");
    enabledLabel.append(enabled, document.createTextNode("启用此服务商"));
    const tools = element("div", "yton-ai-inline");
    const read = button("读取模型", () => remote("models"));
    const test = button("测试连接", () => remote("test"));
    test.title = "检查模型列表接口是否可用，不发起文本生成请求。";
    tools.append(read, test);
    const modelSection = element("section", "yton-ai-models");
    const modelTitle = element("h3", "", "模型");
    const addRow = element("div", "yton-ai-inline");
    const modelInput = input("", "输入或选择模型 ID", () => {});
    modelInput.setAttribute("aria-label", "模型 ID");
    const suggestions = element("datalist");
    suggestions.id = `yton-ai-models-${provider.id}`;
    modelInput.setAttribute("list", suggestions.id);
    function addModel() {
      const id = modelInput.value.trim();
      if (!id) return;
      if (!provider.models.includes(id)) provider.models.push(id);
      modelInput.value = "";
      normalizeDefault();
      renderModels();
      renderProviders();
    }
    modelInput.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); addModel(); } });
    addRow.append(modelInput, button("添加", addModel));
    const modelList = element("div", "yton-ai-model-list");
    function renderModels() {
      modelList.replaceChildren(...provider.models.map(model => {
        const row = element("div", "yton-ai-model-row");
        const label = element("label", "yton-ai-model-choice");
        const radio = element("input");
        radio.type = "radio";
        radio.name = "yton-ai-default-model";
        radio.disabled = !provider.enabled;
        radio.checked = settings.defaultModel === modelReference(provider.id, model);
        radio.title = "设为默认模型";
        radio.addEventListener("change", () => { settings.defaultModel = modelReference(provider.id, model); renderModels(); });
        label.append(radio, element("span", "", model));
        const remove = button("×", () => {
          provider.models = provider.models.filter(item => item !== model);
          normalizeDefault(); renderModels(); renderProviders();
        }, "yton-ai-icon");
        remove.title = `移除 ${model}`;
        remove.setAttribute("aria-label", remove.title);
        row.append(label, ...(radio.checked ? [element("small", "yton-ai-badge", "默认")] : []), remove);
        return row;
      }));
    }
    renderModels();
    modelSection.append(modelTitle, addRow, suggestions, modelList);
    const bottom = element("div", "yton-ai-editor-bottom");
    bottom.append(enabledLabel, button("删除服务商", () => {
      settings.providers = settings.providers.filter(item => item.id !== provider.id);
      selectedId = settings.providers[0]?.id;
      normalizeDefault(); render();
    }, "yton-ai-danger"));
    editor.append(field("服务商名称", name), field("服务地址", baseUrl), field("API Key", keyRow), tools, modelSection, bottom);

    async function remote(path) {
      if (busy) return;
      setBusy(true);
      report(path === "models" ? "正在读取模型…" : "正在测试连接…");
      try {
        const data = await request(path, provider);
        if (!dialog.open) return;
        if (path === "models") {
          suggestions.replaceChildren(...data.models.map(id => {
            const option = element("option"); option.value = id; return option;
          }));
          modelInput.placeholder = "输入模型 ID，或点击选择读取到的模型";
          report(`已读取 ${data.models.length} 个模型，在模型输入框选择后添加。`);
          modelInput.focus();
        } else report(data.message);
      } catch (error) { report(error.message, true); }
      finally { setBusy(false); }
    }
  }

  function setBusy(value) {
    busy = value;
    for (const control of content.querySelectorAll("button, input")) control.disabled = value;
    save.disabled = value;
    if (!value) {
      const provider = settings.providers.find(item => item.id === selectedId);
      if (provider && !provider.enabled) for (const radio of editor.querySelectorAll('input[type="radio"]')) radio.disabled = true;
    }
  }

  async function saveSettings() {
    if (busy) return;
    normalizeDefault();
    setBusy(true);
    report("正在保存…");
    try {
      const saved = await request("settings", settings);
      settingsEvents.dispatchEvent(new CustomEvent("change", { detail: saved }));
      dialog.close();
    } catch (error) { report(error.message, true); }
    finally { setBusy(false); }
  }

  try {
    settings = await request("settings");
    if (!dialog.open) return;
    selectedId = settings.providers[0]?.id;
    report(""); render(); save.disabled = false;
  } catch (error) { report(error.message, true); }
}
