import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { mountNodePanel } from "./node_panel.js";

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

  function value(kind, index) { return String(widgets.get(`${kind}_${index + 1}`)?.value || "").trim(); }
  function changeSlots(changes) {
    node.graph?.beforeChange();
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

  async function upload(files, category, startIndex) {
    if (uploading) return;
    uploading = true;
    clearFeedback();
    const notices = [];
    let next = startIndex;
    try {
      for (const file of files) {
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
          const filename = [result.subfolder, result.name].filter(Boolean).join("/");
          changeSlots([[`${category.kind}_${next + 1}`, filename]]);
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
    const card = document.createElement("div");
    card.className = `yton-media-item${filename ? " has-media" : " is-empty"}`;
    card.dataset.slot = `${section.kind}_${index + 1}`;
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `${section.label.slice(2)} ${index + 1}：${filename ? filename.split("/").pop() : "点击或拖入文件"}`);
    const pick = () => { if (!uploading) { section.selectedSlot = index; section.input.click(); } };
    card.onclick = pick;
    card.onkeydown = event => {
      if (event.target === card && ["Enter", " "].includes(event.key)) { event.preventDefault(); pick(); }
    };
    if (filename) {
      card.draggable = true;
      const source = document.createElement(section.kind === "image" ? "img" : section.kind);
      source.className = "yton-media-thumb";
      source.src = fileURL(filename);
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
      const label = document.createElement("span");
      label.className = "yton-media-filename";
      label.textContent = filename.split("/").pop();
      label.title = filename;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "yton-remove-btn";
      remove.innerHTML = svg('<path d="m6 6 12 12M18 6 6 18"/>');
      remove.setAttribute("aria-label", `移除${section.label.slice(2)} ${index + 1}`);
      remove.onclick = event => { event.stopPropagation(); changeSlots([[`${section.kind}_${index + 1}`, ""]]); };
      card.append(label, remove);
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
        if (from !== index) changeSlots([[`${section.kind}_${from + 1}`, filename], [`${section.kind}_${index + 1}`, value(section.kind, from)]]);
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
  const removed = node.onRemoved;
  node.onRemoved = function () {
    panel.querySelectorAll("audio, video").forEach(source => source.pause());
    return removed?.apply(this, arguments);
  };
  render();
  node.setSize([640, node.size[1]]);
  mountNodePanel(node, "media_loader_ui", panel, 420, 520);
}
