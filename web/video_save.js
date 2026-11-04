import { app } from "../../scripts/app.js";
import { mountNodePanel, followNodeColours } from "./js/node_panel.js";
import { createPathEditor } from "./js/video_path_editor.js";

const style = document.createElement("link");
style.rel = "stylesheet";
style.href = new URL("./css/video_save.css", import.meta.url).href;
document.head.append(style);

export function setupVideoSave(node) {
  const widget = node.widgets.find(item => item.name === "save_path");
  if (!widget) return;
  widget.type = "hidden";
  widget.hidden = true;
  widget.computeSize = () => [0, 0];
  widget.computeLayoutSize = () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
  widget.draw = () => {};
  if (widget.element) widget.element.style.display = "none";
  const panel = document.createElement("div");
  panel.className = "yton-video-save";
  const heading = document.createElement("div");
  heading.className = "yton-video-save-heading";
  heading.textContent = "保存路径";
  const hint = document.createElement("span");
  hint.textContent = "output /";
  hint.title = "目录与文件名前缀，扩展名由格式决定";
  heading.append(hint);
  const path = createPathEditor(widget.value, value => {
    widget.value = value;
    widget.callback?.(value);
    node.graph?.setDirtyCanvas(true, true);
  });
  const status = document.createElement("div");
  status.className = "yton-video-save-status";
  status.hidden = true;
  const player = document.createElement("video");
  player.controls = true;
  player.preload = "metadata";
  player.hidden = true;
  panel.append(heading, path.root, status, player);
  followNodeColours(node, panel);
  mountNodePanel(node, "video_save_panel", panel, 340, 138, { fitHeight: true });

  const callback = widget.callback;
  widget.callback = function (value) {
    const result = callback?.apply(this, arguments);
    if (path.getValue() !== value) path.setValue(value);
    return result;
  };
  const configure = node.onConfigure;
  node.onConfigure = function () {
    const result = configure?.apply(this, arguments);
    path.setValue(widget.value);
    return result;
  };
  function showResult(message) {
    const result = message.yton_video_save?.[0];
    if (!result) return;
    status.hidden = false;
    status.classList.toggle("has-warning", Boolean(result.warnings?.length));
    status.textContent = result.saved ? `已保存：${result.path}` : "未保存，已继续输出视频。查看日志了解原因。";
    status.title = [result.path, ...(result.warnings ?? [])].filter(Boolean).join("\n");
    const file = message.images?.[0];
    player.hidden = !file;
    if (file) {
      const query = new URLSearchParams({ filename: file.filename, subfolder: file.subfolder, type: file.type });
      player.src = `/view?${query}`;
    } else {
      player.removeAttribute("src");
    }
  }
  const executed = node.onExecuted;
  node.onExecuted = function (message) {
    const result = executed?.apply(this, arguments);
    showResult(message);
    return result;
  };
  const removed = node.onRemoved;
  node.onRemoved = function () {
    player.pause();
    player.removeAttribute("src");
    return removed?.apply(this, arguments);
  };
}

app.registerExtension({
  name: "yton.VideoSave",
  nodeCreated(node) {
    if (node.comfyClass === "YtonVideoSave") setupVideoSave(node);
  },
});
