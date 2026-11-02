import { button, el, request } from "./replacement_common.js";

export async function openReplacementSkill(panel) {
  const dialog = el("dialog", "yr-skill-dialog");
  const colours = getComputedStyle(panel);
  for (const name of ["--yr-bg", "--yr-fg", "--yr-field", "--yr-line", "--yr-accent"]) {
    dialog.style.setProperty(name, colours.getPropertyValue(name));
  }
  const heading = el("header", "yr-row");
  const title = el("strong", "", "人物替换 · 提示词优化 Skill");
  title.id = `yr-skill-${crypto.randomUUID()}`;
  dialog.setAttribute("aria-labelledby", title.id);
  heading.append(title, button("关闭", () => dialog.close()));
  const steps = el("ol", "yr-skill-steps");
  for (const text of [
    "根据视频编辑与分段计划准备当前片段，在片段内等间隔抽取六帧，按时间顺序拼成一张带时间标记的图片，作为 <Video 1> 的画面信息。",
    "把已填参考图按槽位顺序排列，应用图片缩放比例，编号为 <Picture 1>、<Picture 2>……；视频拼图不占用 Picture 编号。",
    "读取当前段的原始要求，解析素材引用；开启全段共用时读取共用要求。把视频拼图、参考图、片段序号和用户要求一起交给 LLM 连接器。",
    "LLM 按下方实际 Skill 编写五部分中文提示词。自动优化使用同一套规则；全段共用并自动优化时，每次工作流运行生成一份供所有片段使用。",
  ]) steps.append(el("li", "", text));
  const label = el("label", "yr-field");
  const content = el("textarea", "yr-input yr-skill-content");
  content.readOnly = true;
  content.setAttribute("aria-label", "实际使用的优化 Skill");
  content.value = "正在读取…";
  label.append(el("span", "yr-label", "实际使用的 Skill · 只读"), content);
  dialog.append(heading, steps, label);
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  dialog.showModal();
  try {
    const data = await request("replacement/skill");
    content.value = data.skill;
  } catch (error) {
    content.value = error.message;
  }
}
