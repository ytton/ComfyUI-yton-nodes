import { api } from "../../../scripts/api.js";
import { button, el, mediaURL, request } from "./replacement_common.js";

export function openReplacementAnchors(owner, config, index, save) {
  const dialog = el("dialog", "yr-anchor-dialog");
  const style = getComputedStyle(owner);
  for (const name of ["--yr-bg", "--yr-fg", "--yr-line", "--yr-field", "--yr-accent"])
    dialog.style.setProperty(name, style.getPropertyValue(name));
  const lifetime = new AbortController();
  const uploading = new Set();
  let activeMarker = null;
  const colors = ["#f3ca52", "#ff8066", "#65cba8", "#83b5f5", "#c29af0", "#ec9cc0"];
  let closed = false, info, markers = [], frameCallback;
  const screenshots = new Map();
  const imageURLs = new Set();
  const header = el("header", "yr-anchor-header");
  const title = el("div");
  title.id = `yr-anchors-${crypto.randomUUID()}`;
  dialog.setAttribute("aria-labelledby", title.id);
  title.append(el("strong", "", "关键帧替换"), el("span", "yr-muted", `第 ${index + 1} 段`));
  const close = button("×", () => dialog.close(), "关闭关键帧替换");
  header.append(title, close);
  const stage = el("div", "yr-anchor-stage");
  const video = el("video");
  video.preload = "auto"; video.playsInline = true;
  const counter = el("span", "yr-anchor-counter", "正在准备当前片段…");
  counter.setAttribute("aria-live", "off");
  const play = button("▶", togglePlayback, "播放 / 暂停");
  play.classList.add("yr-anchor-play");
  stage.append(video, counter, play);
  const timeline = el("div", "yr-anchor-timeline");
  const strip = el("img", "yr-anchor-strip");
  strip.alt = "当前片段帧缩略图"; strip.draggable = false;
  const slider = el("input", "yr-anchor-slider");
  slider.type = "range"; slider.min = "0"; slider.step = "1"; slider.value = "0";
  slider.disabled = true; slider.setAttribute("aria-label", "当前帧");
  const pins = el("div", "yr-anchor-pins");
  const ruler = el("div", "yr-anchor-ruler");
  const track = el("div", "yr-anchor-track");
  track.append(strip, slider, pins);
  timeline.append(ruler, track);
  const actions = el("div", "yr-anchor-actions");
  const capture = button("＋ 收集当前帧", collect, "收集当前帧（C）");
  capture.disabled = true;
  const hint = el("span", "yr-muted");
  hint.append(el("kbd", "", "C"), document.createTextNode(" 截取当前帧 · ← → 逐帧 · 空格播放"));
  actions.append(capture, hint);
  const listHeading = el("div", "yr-anchor-list-heading");
  const progress = el("span", "yr-muted");
  listHeading.append(el("strong", "", "替换帧"), progress);
  const list = el("div", "yr-anchor-list");
  const status = el("div", "yr-anchor-status");
  status.setAttribute("role", "status");
  const footer = el("footer", "yr-anchor-footer");
  footer.append(el("span", "yr-muted", "自动保存 · 仅已上传的替换图片参与生成"), button("完成", () => dialog.close()));
  dialog.append(header, stage, timeline, actions, listHeading, list, status, footer);
  const persist = () => save(info.key, markers.map(({ frame, image, stale }) => ({ frame, image, stale: Boolean(stale) })));
  const videoName = config.video.split(/[\\/]/).at(-1).replace(/\.[^.]+$/, "");
  const frameName = frame => `${videoName}_第${frame + 1}帧.png`;
  const currentFrame = () => Math.max(0, Math.min(info.frames - 1, Math.floor(video.currentTime * info.fps + 0.01)));

  function sync() {
    if (!info || closed) return;
    const frame = currentFrame();
    slider.value = String(frame);
    counter.textContent = `${frame + 1} / ${info.frames} 帧`;
    play.textContent = video.paused ? "▶" : "Ⅱ";
    play.classList.toggle("playing", !video.paused);
  }
  function seek(frame) {
    if (!info) return;
    video.pause();
    video.currentTime = (Math.max(0, Math.min(info.frames - 1, frame)) + 0.1) / info.fps;
    sync();
  }
  async function togglePlayback() {
    if (!info) return;
    try {
      if (video.paused) {
        if (video.ended) seek(0);
        await video.play();
      } else video.pause();
    } catch (error) { status.textContent = error.message; }
  }
  function playbackTick() {
    sync();
    if (!closed && !video.paused && video.requestVideoFrameCallback)
      frameCallback = video.requestVideoFrameCallback(playbackTick);
  }
  function selectMarker(marker, preview = true) {
    activeMarker = marker;
    for (const [i, item] of markers.entries()) {
      list.querySelector(`[data-marker="${i}"]`)?.classList.toggle("selected", item === marker);
      const pin = pins.querySelector(`[data-marker="${i}"]`);
      pin?.classList.toggle("selected", item === marker);
      pin?.setAttribute("aria-current", String(item === marker));
    }
    if (preview) seek(marker.frame);
  }
  function renderRuler() {
    ruler.replaceChildren();
    for (let i = 0; i <= 8; i++) {
      const tick = el("span", "", `${Math.round((info.frames - 1) * i / 8) + 1}`);
      tick.style.left = `${i / 8 * 100}%`;
      ruler.append(tick);
    }
    ruler.setAttribute("aria-label", "片段帧刻度");
  }
  function updatePin(pin, marker) {
    pin.style.left = `${marker.frame / Math.max(1, info.frames - 1) * 100}%`;
    pin.setAttribute("aria-valuenow", String(marker.frame + 1));
    pin.title = `第 ${marker.frame + 1} 帧 · 拖动调整位置`;
    pin.classList.toggle("ready", Boolean(marker.image) && !marker.stale);
  }
  function availableFrame(marker, requested) {
    const frame = Math.max(0, Math.min(info.frames - 1, Math.round(requested)));
    const occupied = new Set(markers.filter(item => item !== marker).map(item => item.frame));
    for (let distance = 0; distance < info.frames; distance++) {
      for (const candidate of [frame + distance, frame - distance])
        if (candidate >= 0 && candidate < info.frames && !occupied.has(candidate)) return candidate;
    }
    return marker.frame;
  }
  function moveMarker(marker, requested) {
    const frame = availableFrame(marker, requested);
    if (marker.frame === frame) return false;
    if (marker.image) marker.stale = true;
    marker.frame = frame;
    seek(frame);
    return true;
  }
  function renderPins() {
    pins.replaceChildren();
    for (const [i, marker] of markers.entries()) {
      const pin = el("button", "yr-anchor-pin");
      pin.type = "button";
      pin.dataset.marker = String(i);
      pin.style.setProperty("--marker-color", colors[i % colors.length]);
      pin.append(el("span", "", String(i + 1)));
      pin.setAttribute("role", "slider");
      pin.setAttribute("aria-label", `调整关键帧 ${i + 1}`);
      pin.setAttribute("aria-valuemin", "1");
      pin.setAttribute("aria-valuemax", String(info.frames));
      updatePin(pin, marker);
      pin.classList.toggle("selected", marker === activeMarker);
      pin.addEventListener("click", () => selectMarker(marker));
      pin.addEventListener("pointerdown", event => {
        if (event.button !== 0) return;
        event.preventDefault(); event.stopPropagation();
        selectMarker(marker); pin.focus();
        pin.setPointerCapture(event.pointerId);
        const bounds = track.getBoundingClientRect();
        const originX = event.clientX, originFrame = marker.frame;
        let moved = false;
        const move = event => {
          const target = originFrame + (event.clientX - originX) / bounds.width * Math.max(1, info.frames - 1);
          moved = moveMarker(marker, target) || moved;
          updatePin(pin, marker);
          const card = list.querySelector(`[data-marker="${i}"]`);
          const input = card?.querySelector("input[type=number]");
          if (input) input.value = String(marker.frame + 1);
          if (card) card.dataset.frame = String(marker.frame);
        };
        const finish = () => {
          pin.removeEventListener("pointermove", move);
          pin.removeEventListener("pointerup", finish);
          pin.removeEventListener("pointercancel", finish);
          pin.removeEventListener("lostpointercapture", finish);
          if (moved) { persist(); renderList(); }
        };
        pin.addEventListener("pointermove", move);
        pin.addEventListener("pointerup", finish);
        pin.addEventListener("pointercancel", finish);
        pin.addEventListener("lostpointercapture", finish);
      });
      pins.append(pin);
    }
    progress.textContent = `${markers.filter(marker => marker.image && !marker.stale).length} / ${markers.length} 已上传`;
  }
  function imageCard(image, caption) {
    const card = el("div", "yr-anchor-image");
    if (image) { const img = el("img"); img.src = mediaURL(image); img.alt = caption; card.append(img); }
    return card;
  }
  async function screenshot(frame, card, download) {
    try {
      if (!screenshots.has(frame)) screenshots.set(frame, request("replacement/anchor-frame", { config, index, frame }).then(async data => {
        const response = await fetch(mediaURL(data.image), { signal: lifetime.signal });
        if (!response.ok) throw new Error(`原帧读取失败（${response.status}）`);
        const image = await response.blob();
        lifetime.signal.throwIfAborted();
        const url = URL.createObjectURL(image);
        imageURLs.add(url);
        return url;
      }));
      const url = await screenshots.get(frame);
      if (closed || !card.isConnected) return;
      const img = el("img"); img.src = url; img.alt = `原帧 ${frame + 1}`;
      card.prepend(img);
      download.href = url; download.download = frameName(frame);
      download.removeAttribute("aria-disabled");
    } catch (error) { screenshots.delete(frame); if (!closed) status.textContent = error.message; }
  }
  function renderList() {
    list.replaceChildren(); renderPins();
    if (!markers.length) { list.append(el("div", "yr-anchor-empty", "拖动播放头定位画面，按 C 收集需要替换的帧")); return; }
    for (const [i, marker] of markers.entries()) {
      const card = el("section", "yr-anchor-card");
      card.dataset.frame = String(marker.frame); card.dataset.marker = String(i);
      card.style.setProperty("--marker-color", colors[i % colors.length]);
      card.classList.toggle("selected", marker === activeMarker);
      card.addEventListener("pointerdown", () => selectMarker(marker, false));
      const heading = el("div", "yr-anchor-card-header");
      const badge = button(String(i + 1), () => selectMarker(marker), `选择关键帧 ${i + 1}`);
      badge.classList.add("yr-anchor-badge");
      const position = el("label", "yr-anchor-position");
      const frameInput = el("input");
      frameInput.type = "number"; frameInput.min = "1"; frameInput.max = String(info.frames);
      frameInput.step = "1"; frameInput.value = String(marker.frame + 1);
      frameInput.setAttribute("aria-label", `关键帧 ${i + 1} 的帧号`);
      frameInput.addEventListener("change", () => {
        if (Number.isFinite(frameInput.valueAsNumber) && moveMarker(marker, frameInput.valueAsNumber - 1)) persist();
        renderList();
      });
      position.append(document.createTextNode("第 "), frameInput, document.createTextNode(" 帧"));
      const remove = button("移除", () => {
        markers = markers.filter(item => item !== marker);
        if (activeMarker === marker) activeMarker = markers[0] || null;
        persist(); renderList();
      }, `移除第 ${marker.frame + 1} 帧`);
      remove.classList.add("yr-anchor-remove");
      heading.append(badge, position, remove);
      const pair = el("div", "yr-anchor-pair");
      const sourceColumn = el("div", "yr-anchor-column");
      const editColumn = el("div", "yr-anchor-column");
      const original = imageCard(null, "原帧");
      original.addEventListener("click", () => selectMarker(marker));
      const download = el("a", "yr-button yr-anchor-download", "下载原帧");
      download.setAttribute("aria-label", `下载第 ${marker.frame + 1} 帧`);
      download.setAttribute("aria-disabled", "true");
      sourceColumn.append(el("span", "yr-muted", "原帧"), original, download);
      const replacement = imageCard(marker.image, "替换帧");
      replacement.classList.toggle("empty", !marker.image);
      if (!marker.image) replacement.append(el("span", "yr-anchor-upload-hint", "拖入、粘贴或上传替换图片"));
      const file = el("input"); file.type = "file"; file.accept = "image/*"; file.hidden = true;
      file.setAttribute("aria-label", `上传第 ${marker.frame + 1} 帧的替换图片`);
      const uploadButton = button(uploading.has(marker) ? "上传中…" : marker.image ? "更换图片" : "上传图片", () => file.click(), `上传第 ${marker.frame + 1} 帧的替换图片`);
      uploadButton.classList.add("yr-anchor-upload");
      uploadButton.disabled = uploading.has(marker);
      replacement.addEventListener("click", () => file.click());
      replacement.addEventListener("dragover", event => { event.preventDefault(); replacement.classList.add("drag-over"); });
      replacement.addEventListener("dragleave", () => replacement.classList.remove("drag-over"));
      replacement.addEventListener("drop", event => {
        event.preventDefault(); replacement.classList.remove("drag-over");
        void upload(event.dataTransfer.files[0], marker, uploadButton);
      });
      file.addEventListener("change", () => { void upload(file.files[0], marker, uploadButton); });
      editColumn.append(el("span", "yr-muted", "替换帧"), replacement, uploadButton);
      pair.append(sourceColumn, editColumn);
      const note = el("div", "yr-anchor-card-note");
      const message = el("span", marker.stale ? "stale" : "yr-muted", marker.stale ? "帧位置已调整，请上传对应的替换图" : marker.image ? "替换图已就绪" : "下载原帧 → 编辑 → 上传替换图");
      note.append(message);
      if (marker.image) note.append(button("清空", () => { marker.image = ""; marker.stale = false; persist(); renderList(); }, `清空第 ${marker.frame + 1} 帧的替换图片`));
      card.append(heading, pair, note, file);
      list.append(card); void screenshot(marker.frame, original, download);
    }
  }
  function collect() {
    if (!info) return;
    video.pause();
    const frame = currentFrame();
    if (!markers.some(marker => marker.frame === frame)) {
      const marker = { frame, image: "", stale: false };
      markers.push(marker); activeMarker = marker;
      persist(); renderList();
    }
    selectMarker(markers.find(marker => marker.frame === frame), false);
    list.querySelector(`[data-frame="${frame}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  async function upload(file, marker, control) {
    if (!file || uploading.has(marker)) return;
    if (!file.type.startsWith("image/")) { status.textContent = "请选择图片文件。"; return; }
    uploading.add(marker);
    const uploadedFrame = marker.frame;
    control.disabled = true; control.textContent = "上传中…"; status.textContent = "";
    try {
      const body = new FormData();
      body.append("image", file, `${crypto.randomUUID()}.${file.name.split(".").at(-1)}`);
      body.append("type", "input"); body.append("subfolder", `yton-replacement/anchors/${info.key}`);
      const response = await api.fetchApi("/upload/image", { method: "POST", body });
      if (!response.ok) throw new Error(`上传失败（${response.status}）`);
      const data = await response.json();
      if (!data.name) throw new Error("上传没有返回图片文件名。");
      if (closed || !markers.includes(marker)) return;
      marker.image = [data.subfolder, data.name].filter(Boolean).join("/");
      marker.stale = marker.frame !== uploadedFrame; persist();
    } catch (error) { if (!closed) status.textContent = error.message; }
    finally { uploading.delete(marker); if (!closed) renderList(); }
  }
  slider.addEventListener("input", () => seek(Number(slider.value)));
  slider.addEventListener("pointerdown", () => video.pause());
  for (const event of ["timeupdate", "seeked", "pause", "ended", "loadeddata"]) video.addEventListener(event, sync);
  video.addEventListener("play", () => { sync(); playbackTick(); });
  video.addEventListener("pause", () => {
    if (frameCallback !== undefined) video.cancelVideoFrameCallback?.(frameCallback);
    frameCallback = undefined;
  });
  document.addEventListener("keydown", event => {
    if (!dialog.open) return;
    event.stopImmediatePropagation();
    const markerPin = event.target instanceof Element ? event.target.closest(".yr-anchor-pin") : null;
    if (markerPin && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const marker = markers[Number(markerPin.dataset.marker)];
      const target = event.key === "Home" ? 0 : event.key === "End" ? info.frames - 1 : marker.frame + (event.key === "ArrowRight" ? 1 : -1);
      if (moveMarker(marker, target)) { persist(); renderList(); pins.querySelector(`[data-marker="${markers.indexOf(marker)}"]`)?.focus(); }
      return;
    }
    if (event.target instanceof Element && event.target.closest("input:not([type='range']),textarea,[contenteditable='true']")) return;
    if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key.toLowerCase() === "c") { event.preventDefault(); collect(); }
    else if (event.code === "Space") { event.preventDefault(); void togglePlayback(); }
    else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault(); if (info) seek(currentFrame() + (event.key === "ArrowRight" ? 1 : -1));
    }
  }, { capture: true, signal: lifetime.signal });
  document.addEventListener("paste", event => {
    if (!dialog.open || !activeMarker) return;
    const file = Array.from(event.clipboardData?.files || []).find(file => file.type.startsWith("image/"));
    if (!file) return;
    event.preventDefault(); event.stopImmediatePropagation();
    const control = list.querySelector(`[data-marker="${markers.indexOf(activeMarker)}"] .yr-anchor-upload`);
    void upload(file, activeMarker, control);
  }, { capture: true, signal: lifetime.signal });
  for (const event of ["pointerdown", "keydown", "wheel", "drop", "paste"])
    dialog.addEventListener(event, event => event.stopPropagation());
  dialog.addEventListener("close", () => {
    closed = true; lifetime.abort(); video.pause();
    for (const url of imageURLs) URL.revokeObjectURL(url);
    if (frameCallback !== undefined) video.cancelVideoFrameCallback?.(frameCallback);
    video.removeAttribute("src"); video.load(); dialog.remove(); closeHook();
  }, { once: true });
  let closeHook = () => {};
  document.body.append(dialog); dialog.showModal();
  void request("replacement/anchor-preview", { config, index }).then(data => {
    if (closed) return;
    info = data; markers = structuredClone(config.anchors?.[info.key] || []);
    video.src = mediaURL(info.video); strip.src = mediaURL(info.strip);
    slider.max = String(info.frames - 1); slider.disabled = false; capture.disabled = false;
    activeMarker = markers[0] || null;
    renderRuler(); renderList(); sync();
  }).catch(error => { if (!closed) { status.textContent = error.message; counter.textContent = "片段加载失败"; } });
  return { close: () => dialog.close(), onClose: callback => { closeHook = callback; } };
}
