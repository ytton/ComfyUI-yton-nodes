import { button, element, field } from "./prompt_optimizer_api.js";

export function openLlamaSettings(raw, catalogue, save, native = false) {
  const dialog = element("dialog", "yton-ai-dialog yton-llama-dialog");
  const heading = element("h2", "", native ? "ComfyUI 原生推理设置" : "llama.cpp 推理设置");
  heading.id = `yton-llama-${crypto.randomUUID()}`;
  dialog.setAttribute("aria-labelledby", heading.id);
  const close = () => dialog.close();
  const header = element("div", "yton-ai-dialog-header");
  const dismiss = button("×", close, "yton-ai-icon");
  dismiss.setAttribute("aria-label", "关闭设置");
  header.append(heading, dismiss);
  const form = element("form", "yton-llama-form");
  const body = element("div", "yton-llama-body");
  const status = element("div", "yton-ai-status");
  status.setAttribute("role", "status");
  const controls = new Map();
  let draft;
  try { draft = JSON.parse(raw); }
  catch { throw new Error("本地推理设置不是有效 JSON。"); }

  function choiceControl(spec, choices) {
    const menu = element("details", "yton-ai-model-menu");
    const label = element("summary");
    const options = element("div", "yton-ai-model-options");
    const update = () => label.textContent = choices.find(([value]) => value === draft[spec.key])?.[1] || String(draft[spec.key]);
    options.append(...choices.map(([value, text]) => button(text, () => {
      draft[spec.key] = value; update(); menu.open = false;
      if (spec.key === "thinking") {
        const budget = { off: 0, low: 512, medium: 2048, high: 8192, custom: draft.reasoning_budget }[value];
        if (budget >= draft.max_tokens) {
          draft.max_tokens = budget + 2048;
          controls.get("max_tokens").value = draft.max_tokens;
        }
      }
      sync();
    })));
    label.setAttribute("aria-label", spec.label);
    menu.append(label, options); update();
    return menu;
  }
  for (const group of ["采样", "思考", "加载"]) {
    if (!catalogue.fields.some(item => item.group === group)) continue;
    const section = element("section", "yton-llama-section");
    section.append(element("h3", "", group === "加载" ? "模型加载与显存" : group));
    const grid = element("div", "yton-llama-grid");
    for (const spec of catalogue.fields.filter(item => item.group === group)) {
      let control;
      if (spec.choices || spec.catalogue) {
        const choices = spec.choices || [["auto", "自动匹配同目录"], ["", "不使用（纯文本）"], ...catalogue[spec.catalogue].map(name => [name, name])];
        control = choiceControl(spec, choices);
      } else {
        control = element("input", "yton-ai-input");
        if (typeof spec.default === "boolean") {
          control.type = "checkbox";
          control.checked = draft[spec.key];
          control.addEventListener("change", () => draft[spec.key] = control.checked);
        } else {
          control.type = "number";
          control.min = spec.min; control.max = spec.max; control.step = spec.step;
          control.required = true; control.value = draft[spec.key];
          control.addEventListener("input", () => { draft[spec.key] = Number(control.value); sync(); });
        }
        control.setAttribute("aria-label", spec.label);
      }
      controls.set(spec.key, control);
      const wrapper = field(spec.label, control);
      if (spec.help) { wrapper.title = spec.help; control.title = spec.help; }
      if (typeof spec.default === "boolean") wrapper.classList.add("yton-ai-check", "yton-llama-check");
      grid.append(wrapper);
    }
    section.append(grid); body.append(section);
  }
  function sync() {
    const budgetControl = controls.get("reasoning_budget");
    if (budgetControl) budgetControl.disabled = draft.thinking !== "custom";
    status.textContent = "";
  }
  const footer = element("div", "yton-ai-dialog-footer");
  const submit = element("button", "yton-ai-button yton-ai-primary", "保存");
  submit.type = "submit";
  footer.append(status, button("取消", close), submit);
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const fail = text => { status.textContent = text; status.classList.add("yton-ai-error"); };
    if (!native) {
      if (draft.max_tokens >= draft.n_ctx) return fail("最大输出 Token 必须小于模型上下文。");
      if (draft.n_ubatch > draft.n_batch) return fail("物理批次不能大于逻辑批次。");
      if (draft.image_min_tokens > draft.image_max_tokens) return fail("图片最少 Token 不能大于图片最多 Token。");
      if (draft.kv_cache_type !== "f16" && !draft.flash_attn) return fail("量化 KV 缓存需要启用 Flash Attention。");
    }
    const budget = native ? 0 : { off: 0, low: 512, medium: 2048, high: 8192, custom: draft.reasoning_budget }[draft.thinking];
    if (budget >= draft.max_tokens) return fail("最大输出 Token 需大于思考预算。");
    save(JSON.stringify(draft)); close();
  });
  sync(); form.append(body, footer); dialog.append(header, form);
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  document.body.append(dialog); dialog.showModal();
}
