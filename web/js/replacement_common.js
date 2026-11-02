import { api } from "../../../scripts/api.js";

export const el = (tag, className = "", text) => {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
export function button(text, action, title = text) {
  const control = el("button", "yr-button", text);
  control.type = "button";
  control.title = title;
  control.setAttribute("aria-label", title);
  control.addEventListener("click", action);
  return control;
}
export function input(value, onChange, { type = "number", min, max, step = "any", label = "" } = {}) {
  const control = el("input", "yr-input");
  Object.assign(control, { type, value, step });
  if (min !== undefined) control.min = min;
  if (max !== undefined) control.max = max;
  if (label) control.setAttribute("aria-label", label);
  control.addEventListener("change", () => onChange(type === "number" ? control.valueAsNumber : control.value));
  return control;
}
export function select(options, value, onChange, label) {
  const control = el("select", "yr-input");
  control.setAttribute("aria-label", label);
  for (const option of options) {
    const item = el("option", "", typeof option === "object" ? option.label : String(option));
    item.value = typeof option === "object" ? option.value : option;
    control.append(item);
  }
  control.value = String(value);
  control.addEventListener("change", () => onChange(control.value));
  return control;
}
export function field(label, control) {
  const wrapper = el("label", "yr-field");
  wrapper.append(el("span", "yr-label", label), control);
  return wrapper;
}
export function toggle(label, value, change) {
  const checkbox = el("input");
  checkbox.type = "checkbox";
  checkbox.checked = value;
  checkbox.addEventListener("change", () => change(checkbox.checked));
  const wrapper = el("label", "yr-toggle");
  wrapper.append(checkbox, document.createTextNode(label));
  return wrapper;
}
export async function request(path, body) {
  const response = await api.fetchApi(`/yton/${path}`, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}
export function mediaURL(file, kind = "input") {
  if (!file) return "";
  if (typeof file === "string") {
    const clean = file.replace(/\s*\[(input|output|temp)\]$/, "").replaceAll("\\", "/");
    kind = file.match(/\[(input|output|temp)\]$/)?.[1] || kind;
    const slash = clean.lastIndexOf("/");
    file = { filename: clean.slice(slash + 1), subfolder: clean.slice(0, Math.max(0, slash)), type: kind };
  }
  return api.apiURL(`/view?${new URLSearchParams({filename: file.filename, subfolder: file.subfolder || "", type: file.type || kind})}`);
}
export function hideWidget(widget) {
  widget.type = "hidden";
  widget.hidden = true;
  widget.computeSize = () => [0, 0];
  widget.computeLayoutSize = () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
  widget.draw = () => {};
  if (widget.options) widget.options.hidden = true;
  if (widget.element) widget.element.style.display = "none";
}
