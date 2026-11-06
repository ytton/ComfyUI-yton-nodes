import { button, el, request } from "./replacement_common.js";

export async function openReplacementSkill(panel, {endpoint="replacement/skill", titleText="人物替换 · 提示词优化 Skill", steps:customSteps} = {}) {
  const dialog = el("dialog", "yr-skill-dialog");
  const colours = getComputedStyle(panel);
  for (const name of ["--yr-bg", "--yr-fg", "--yr-field", "--yr-line", "--yr-accent"]) {
    dialog.style.setProperty(name, colours.getPropertyValue(name));
  }
  const heading = el("header", "yr-row");
  const title = el("strong", "", titleText);
  title.id = `yr-skill-${crypto.randomUUID()}`;
  dialog.setAttribute("aria-labelledby", title.id);
  let defaultSkill;
  const reset = button("重置为默认", () => {
    content.value = defaultSkill;
    status.textContent = "已恢复默认内容，保存后生效";
    save.disabled = false;
  });
  reset.disabled = true;
  const actions = el("div", "yr-prompt-actions");
  actions.append(reset, button("关闭", () => dialog.close()));
  heading.append(title, actions);
  const steps = el("ol", "yr-skill-steps");
  for (const text of customSteps || [
    "根据视频编辑与分段计划准备当前片段，在片段内等间隔抽取六帧，按时间顺序拼成一张带时间标记的图片，作为 <Video 1> 的画面信息。",
    "把已填参考图按槽位顺序排列，应用图片缩放比例，编号为 <Picture 1>、<Picture 2>……；视频拼图不占用 Picture 编号。",
    "读取当前段的原始要求，解析素材引用；开启全段共用时读取共用要求。把视频拼图、参考图、片段序号和用户要求一起交给 LLM 连接器。",
    "LLM 按下方保存的 Skill 编写提示词。手动与自动优化使用同一套规则；全段共用并自动优化时，每次工作流运行生成一份供所有片段使用。",
  ]) steps.append(el("li", "", text));
  const label = el("label", "yr-field");
  const content = el("textarea", "yr-input yr-skill-content");
  content.disabled = true;
  content.setAttribute("aria-label", "实际使用的优化 Skill");
  content.placeholder = "正在读取…";
  label.append(el("span", "yr-label", "优化 Skill · 保存后生效"), content);
  const footer = el("footer", "yr-row yr-skill-footer");
  const status = el("span", "yr-muted");
  status.setAttribute("role", "status");
  const save = button("保存", async () => {
    save.disabled = true; reset.disabled = true; content.disabled = true;
    status.textContent = "正在保存…";
    try {
      const data = await request(endpoint, {skill: content.value});
      content.value = data.skill;
      status.textContent = "已保存，后续优化使用此 Skill";
    } catch (error) {
      status.textContent = error.message;
    } finally {
      content.disabled = false; reset.disabled = false;
      save.disabled = !content.value.trim();
    }
  });
  save.disabled = true;
  content.addEventListener("input", () => {save.disabled = !content.value.trim(); status.textContent = "尚未保存";});
  footer.append(status, save);
  dialog.append(heading, steps, label, footer);
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  dialog.showModal();
  try {
    const data = await request(endpoint);
    content.value = data.skill;
    defaultSkill = data.default_skill;
    content.disabled = false; reset.disabled = false; save.disabled = !content.value.trim();
  } catch (error) {
    status.textContent = error.message;
  }
}
