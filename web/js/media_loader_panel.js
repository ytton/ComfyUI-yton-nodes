import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { mountNodePanel } from "./node_panel.js";
import { editSlotMask } from "./media_mask_editor.js";
import { openImagePreview } from "./media_image_preview.js";
import { imageChannelURL, showMaskPreview } from "./media_mask_preview.js";

const CATEGORIES = [
  { kind: "image", label: "参考图片", count: 9, accept: "image/*", icon: '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1"/><path d="m3 17 6-6 4 4 3-3 5 5"/>' },
  { kind: "video", label: "参考视频", count: 3, accept: "video/*", icon: '<rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3"/>' },
  { kind: "audio", label: "参考音频", count: 3, accept: "audio/*", icon: '<path d="M3 10v4m4-7v10m5-14v18m5-14v10m4-7v4"/>' },
];
const DRAG_TYPE = "application/x-yton-media-slot";
const svg = content => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${content}</svg>`;
const durationLabel = duration => Number.isFinite(duration)
  ? `${Math.floor(duration / 60)}:${String(Math.floor(duration % 60)).padStart(2, "0")}` : "";

function fileKind(file) {
  const extension = file.name.split(".").pop().toLowerCase();
  if (file.type.startsWith("image/") || /^(png|jpe?g|webp|gif|bmp|tiff?|avif)$/.test(extension)) return "image";
  if (file.type.startsWith("video/") || /^(mp4|webm|mov|avi|mkv|m4v)$/.test(extension)) return "video";
  if (file.type.startsWith("audio/") || /^(mp3|wav|ogg|flac|m4a|aac|opus)$/.test(extension)) return "audio";
  return null;
}

function fileURL(filename) {
  const clean = filename.replace(/\s*\[(input|output|temp)\]$/, "").replaceAll("\\", "/");
  const type = filename.match(/\[(input|output|temp)\]$/)?.[1] || "input";
  const slash = clean.lastIndexOf("/");
  return api.apiURL(`/view?${new URLSearchParams({ filename: clean.slice(slash + 1), subfolder: clean.slice(0, Math.max(0, slash)), type })}`);
}

export function setupMediaLoaderNode(node) {
  node.properties.ytonMediaCollapsed = { image: false, video: true, audio: true };
  // ComfyUI's Vue renderer adds sockets for primitive widgets automatically.
  // These file fields belong exclusively to the slot panel.
  node.onConnectInput = () => false;
  const widgets = new Map((node.widgets || []).map(widget => [widget.name, widget]));
  for (const widget of widgets.values()) {
    widget.type = "hidden";
    widget.hidden = true;
    widget.computeSize = () => [0, 0];
    widget.computeLayoutSize = () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
    widget.draw = () => {};
    if (widget.options) widget.options.hidden = true;
    if (widget.element) widget.element.style.display = "none";
  }
  const panel = document.createElement("div");
  const panelId = crypto.randomUUID();
  panel.className = "yton-panel yton-media-panel";
  const sections = [];
  let uploading = false;
  let draggedSlot = null;
  let removed = false;
  let closePreview = null;

  function value(kind, index) { return String(widgets.get(`${kind}_${index + 1}`)?.value || "").trim(); }
  function disabled(kind, index) { return widgets.get(`disable_${kind}_${index + 1}`).value === true; }
  function changeSlots(changes, expandedKind) {
    node.graph?.beforeChange();
    if (expandedKind) node.properties.ytonMediaCollapsed[expandedKind] = false;
    for (const [name, filename] of changes) {
      const widget = widgets.get(name);
      widget.value = filename;
      widget.callback?.(filename);
    }
    node.graph?.afterChange();
    render();
  }

  function clearFeedback() {
    for (const section of sections) {
      section.error.textContent = "";
      section.grid.querySelectorAll(".drag-over").forEach(card => card.classList.remove("drag-over"));
    }
  }

  async function upload(files, category, startIndex, { expand = false, resetFeedback = true } = {}) {
    if (uploading) return;
    uploading = true;
    if (resetFeedback) clearFeedback();
    const notices = [];
    let next = startIndex;
    try {
      for (const file of files) {
        if (removed) return;
        if (fileKind(file) !== category.kind) { notices.push(`请选择${category.label.slice(2)}文件`); continue; }
        if (next !== startIndex) while (next < category.count && value(category.kind, next)) next++;
        if (next >= category.count) { notices.push(`最多 ${category.count} 个槽位，请先移除素材`); break; }
        const card = category.grid.children[next];
        card.classList.add("uploading");
        const body = new FormData();
        body.append("image", file);
        body.append("type", "input");
        body.append("subfolder", "yton-media");
        try {
          const response = await api.fetchApi("/upload/image", { method: "POST", body });
          if (!response.ok) throw new Error(`上传失败（${response.status}）`);
          const result = await response.json();
          if (!result.name) throw new Error("上传未返回素材文件名");
          if (removed) return;
          const filename = [result.subfolder, result.name].filter(Boolean).join("/");
          changeSlots([[`${category.kind}_${next + 1}`, filename], [`disable_${category.kind}_${next + 1}`, false]], expand ? category.kind : null);
          next++;
        } catch (error) {
          notices.push(`${file.name}：${error.message}`);
          card.classList.remove("uploading");
        }
      }
    } finally {
      uploading = false;
      category.error.textContent = [...new Set(notices)].join("；");
      node.setDirtyCanvas(true, true);
    }
  }

  function pasteMedia(event) {
    if (event.defaultPrevented || removed || node.graph !== app.canvas?.graph) return;
    const target = event.target;
    if (target instanceof Element && target.closest("input, textarea, [contenteditable]:not([contenteditable='false']), [role='textbox']")) return;
    const selected = Object.values(app.canvas.selected_nodes || {});
    // A paste goes to one selected loader, even if several loaders are selected.
    if (selected.find(selectedNode => selectedNode.type === node.type) !== node) return;
    const clipboard = event.clipboardData;
    if (!clipboard) return;
    const files = clipboard.files.length ? Array.from(clipboard.files)
      : Array.from(clipboard.items).filter(item => item.kind === "file").map(item => item.getAsFile()).filter(Boolean);
    const groups = sections.map(category => ({ category, files: files.filter(file => fileKind(file) === category.kind) }))
      .filter(group => group.files.length);
    if (!groups.length) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (uploading) {
      groups[0].category.error.textContent = "素材上传中，请稍后再粘贴";
      return;
    }
    clearFeedback();
    // Upload sequentially so each category keeps its own progress and feedback.
    void (async () => {
      for (const { category, files } of groups) {
        if (removed) return;
        let index = 0;
        while (index < category.count && value(category.kind, index)) index++;
        await upload(files, category, index, { expand: true, resetFeedback: false });
      }
    })();
  }

  function createSection(definition) {
    const section = { ...definition };
    const element = document.createElement("section");
    element.className = "yton-media-section";
    const header = document.createElement("button");
    header.type = "button";
    header.className = "yton-media-row-header";
    header.setAttribute("aria-label", `${section.label} · ${section.count}`);
    header.innerHTML = `<span class="yton-media-category-icon">${svg(section.icon)}</span><span>${section.label} · ${section.count}</span><span class="yton-media-chevron">${svg('<path d="m6 15 6-6 6 6"/>')}</span>`;
    const grid = document.createElement("div");
    grid.className = `yton-media-grid ${section.kind}-grid`;
    grid.id = `yton-${panelId}-${section.kind}-slots`;
    header.setAttribute("aria-controls", grid.id);
    const input = document.createElement("input");
    input.type = "file";
    input.accept = section.accept;
    input.multiple = true;
    input.hidden = true;
    input.setAttribute("aria-label", `选择${section.label.slice(2)}素材`);
    input.onchange = async () => {
      await upload(Array.from(input.files), section, section.selectedSlot);
      input.value = "";
    };
    header.onclick = () => {
      node.graph?.beforeChange();
      node.properties.ytonMediaCollapsed ||= {};
      node.properties.ytonMediaCollapsed[section.kind] = !grid.hidden;
      node.graph?.afterChange();
      render();
    };
    const error = document.createElement("div");
    error.className = "yton-media-error";
    error.setAttribute("role", "status");
    element.append(header, grid, input, error);
    panel.append(element);
    return Object.assign(section, { element, header, grid, input, error, selectedSlot: 0 });
  }

  function renderCard(section, index) {
    const filename = value(section.kind, index);
    const outputDisabled = disabled(section.kind, index);
    const card = document.createElement("div");
    card.className = `yton-media-item${filename ? " has-media" : " is-empty"}${filename && outputDisabled ? " output-disabled" : ""}`;
    card.dataset.slot = `${section.kind}_${index + 1}`;
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `${section.label.slice(2)} ${index + 1}：${filename ? filename.split("/").pop() : "点击或拖入文件"}${filename && outputDisabled ? "（输出已禁用）" : ""}`);
    const pick = () => { if (!uploading) { section.selectedSlot = index; section.input.click(); } };
    card.onclick = pick;
    card.onkeydown = event => {
      if (event.target === card && ["Enter", " "].includes(event.key)) { event.preventDefault(); pick(); }
    };
    if (filename) {
      card.draggable = true;
      const source = document.createElement(section.kind === "image" ? "img" : section.kind);
      source.className = "yton-media-thumb";
      source.src = section.kind === "image" ? imageChannelURL(fileURL(filename), "rgb") : fileURL(filename);
      source.draggable = false;
      if (section.kind === "image") source.alt = filename.split("/").pop();
      else {
        source.preload = "metadata";
        const duration = document.createElement("span");
        duration.className = "yton-badge-duration";
        source.onloadedmetadata = () => { duration.textContent = durationLabel(source.duration); };
        const play = document.createElement("button");
        play.type = "button";
        play.className = "yton-media-play";
        play.setAttribute("aria-label", `播放${section.label.slice(2)} ${index + 1}`);
        play.innerHTML = svg('<path d="m9 5 11 7-11 7z"/>');
        play.onclick = async event => {
          event.stopPropagation();
          try { if (source.paused) await source.play(); else source.pause(); }
          catch { section.error.textContent = "浏览器无法预览此格式，素材仍可用于工作流"; }
        };
        const playing = () => {
          play.innerHTML = svg(source.paused ? '<path d="m9 5 11 7-11 7z"/>' : '<path d="M8 5v14M16 5v14"/>');
          play.setAttribute("aria-label", `${source.paused ? "播放" : "暂停"}${section.label.slice(2)} ${index + 1}`);
        };
        source.onplay = source.onpause = source.onended = playing;
        if (section.kind === "audio") {
          source.hidden = true;
          const wave = document.createElement("span");
          wave.className = "yton-audio-icon";
          wave.innerHTML = svg(section.icon);
          card.append(wave);
        }
        card.append(play, duration);
      }
      card.append(source);
      const output = document.createElement("button");
      output.type = "button";
      output.className = "yton-output-toggle";
      output.title = `${outputDisabled ? "启用" : "禁用"}${section.label.slice(2)} ${index + 1} 输出`;
      output.setAttribute("aria-label", output.title);
      output.setAttribute("aria-pressed", String(outputDisabled));
      output.innerHTML = svg('<path d="M18.4 6.6a9 9 0 1 1-12.8 0"/><path d="M12 2v10"/>');
      output.disabled = uploading;
      output.onpointerdown = event => event.stopPropagation();
      output.onkeydown = event => event.stopPropagation();
      output.ondragstart = event => { event.preventDefault(); event.stopPropagation(); };
      output.onclick = event => {
        event.preventDefault();
        event.stopPropagation();
        changeSlots([[`disable_${section.kind}_${index + 1}`, !outputDisabled]]);
      };
      card.append(output);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "yton-remove-btn";
      remove.innerHTML = svg('<path d="m6 6 12 12M18 6 6 18"/>');
      remove.setAttribute("aria-label", `移除${section.label.slice(2)} ${index + 1}`);
      remove.onclick = event => { event.stopPropagation(); changeSlots([[`${section.kind}_${index + 1}`, ""], [`disable_${section.kind}_${index + 1}`, false]]); };
      card.append(remove);
      if (section.kind === "image") {
        showMaskPreview(card, fileURL(filename));
        const preview = document.createElement("button");
        preview.type = "button";
        preview.className = "yton-preview-btn";
        preview.title = `查看图片 ${index + 1} 大图`;
        preview.setAttribute("aria-label", preview.title);
        preview.innerHTML = svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>');
        preview.onpointerdown = event => event.stopPropagation();
        preview.onkeydown = event => event.stopPropagation();
        preview.ondragstart = event => { event.preventDefault(); event.stopPropagation(); };
        preview.onclick = event => {
          event.preventDefault();
          event.stopPropagation();
          closePreview?.();
          closePreview = openImagePreview(fileURL(filename), filename, preview);
        };
        const mask = document.createElement("button");
        mask.type = "button";
        mask.className = "yton-mask-btn";
        mask.title = `编辑图片 ${index + 1} 遮罩`;
        mask.setAttribute("aria-label", mask.title);
        mask.innerHTML = '<span class="icon-[comfy--mask]" aria-hidden="true"></span>';
        mask.onpointerdown = event => event.stopPropagation();
        mask.onkeydown = event => event.stopPropagation();
        mask.ondragstart = event => { event.preventDefault(); event.stopPropagation(); };
        mask.onclick = async event => {
          event.stopPropagation();
          section.error.textContent = "";
          mask.disabled = true;
          try {
            await editSlotMask(filename, saved => {
              if (!removed && value("image", index) === filename) {
                changeSlots([[`image_${index + 1}`, saved]]);
              }
            });
          } catch (error) {
            section.error.textContent = `遮罩编辑器打开失败：${error.message}`;
          } finally {
            mask.disabled = false;
          }
        };
        card.append(preview, mask);
      }
      card.ondragstart = event => {
        draggedSlot = { kind: section.kind, index };
        event.dataTransfer.setData(DRAG_TYPE, `${section.kind}:${index}`);
        event.dataTransfer.effectAllowed = "move";
        card.classList.add("dragging");
      };
      card.ondragend = () => { draggedSlot = null; card.classList.remove("dragging"); clearFeedback(); };
    } else {
      const placeholder = document.createElement("span");
      placeholder.className = "yton-media-empty";
      placeholder.textContent = "点击或拖入文件";
      card.append(placeholder);
    }
    const number = document.createElement("span");
    number.className = "yton-badge-index";
    number.textContent = String(index + 1);
    card.append(number);
    card.ondragover = event => { event.preventDefault(); event.stopPropagation(); card.classList.add("drag-over"); };
    card.ondragleave = event => { if (!card.contains(event.relatedTarget)) card.classList.remove("drag-over"); };
    card.ondrop = async event => {
      event.preventDefault(); event.stopPropagation(); card.classList.remove("drag-over");
      if (uploading) return;
      if (event.dataTransfer.types.includes(DRAG_TYPE) && draggedSlot?.kind === section.kind) {
        const from = draggedSlot.index;
        draggedSlot = null;
        if (from !== index) changeSlots([
          [`${section.kind}_${from + 1}`, filename], [`${section.kind}_${index + 1}`, value(section.kind, from)],
          [`disable_${section.kind}_${from + 1}`, outputDisabled], [`disable_${section.kind}_${index + 1}`, disabled(section.kind, from)],
        ]);
      } else if (event.dataTransfer.files.length) {
        await upload(Array.from(event.dataTransfer.files), section, index);
      }
    };
    return card;
  }

  function render() {
    while (node.inputs?.length) node.removeInput(node.inputs.length - 1);
    for (const section of sections) {
      section.grid.querySelectorAll("audio, video").forEach(source => source.pause());
      section.grid.replaceChildren(...Array.from({ length: section.count }, (_, index) => renderCard(section, index)));
      const collapsed = Boolean(node.properties?.ytonMediaCollapsed?.[section.kind]);
      section.grid.hidden = collapsed;
      section.header.setAttribute("aria-expanded", String(!collapsed));
    }
    node.setDirtyCanvas(true, true);
  }
  for (const definition of CATEGORIES) sections.push(createSection(definition));
  for (const widget of widgets.values()) {
    const callback = widget.callback;
    widget.callback = function () { const result = callback?.apply(this, arguments); render(); return result; };
  }
  const configure = node.onConfigure;
  node.onConfigure = function () { const result = configure?.apply(this, arguments); render(); return result; };
  window.addEventListener("paste", pasteMedia, true);
  const onRemoved = node.onRemoved;
  node.onRemoved = function () {
    removed = true;
    closePreview?.();
    window.removeEventListener("paste", pasteMedia, true);
    panel.querySelectorAll("audio, video").forEach(source => source.pause());
    return onRemoved?.apply(this, arguments);
  };
  render();
  node.setSize([640, node.size[1]]);
  mountNodePanel(node, "media_loader_ui", panel, 420, 520);
}
