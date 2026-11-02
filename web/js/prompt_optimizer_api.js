import { api } from "../../../scripts/api.js";

export const settingsEvents = new EventTarget();

export async function optimizerRequest(path, body) {
  const response = await api.fetchApi(`/yton/prompt-optimizer/${path}`, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data;
  try { data = await response.json(); }
  catch { throw new Error(`请求失败（HTTP ${response.status}），请检查 ComfyUI 日志。`); }
  if (!response.ok) throw new Error(data.error || `请求失败（HTTP ${response.status}）`);
  return data;
}

export const modelReference = (provider, model) => JSON.stringify([provider, model]);

export function availableModels(settings) {
  return settings.providers.filter(provider => provider.enabled).flatMap(provider =>
    provider.models.map(model => ({ value: modelReference(provider.id, model), label: `${provider.name} · ${model}` })));
}

export function element(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined) result.textContent = text;
  return result;
}

export function button(text, action, className = "") {
  const result = element("button", `yton-ai-button ${className}`, text);
  result.type = "button";
  result.addEventListener("click", action);
  return result;
}

export function field(label, control) {
  const wrapper = element("label", "yton-ai-field");
  wrapper.append(element("span", "", label), control);
  return wrapper;
}

export const GEAR = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m9 3-.6 2.2-1.9 1.1-2.2-.6-3 5.2 1.6 1.6v2.2l-1.6 1.6 3 5.2 2.2-.6 1.9 1.1L9 24h6l.6-2.2 1.9-1.1 2.2.6 3-5.2-1.6-1.6v-2.2l1.6-1.6-3-5.2-2.2.6-1.9-1.1L15 3z" transform="translate(2 0) scale(.83)"/><circle cx="12" cy="11.5" r="3.2"/></svg>';
