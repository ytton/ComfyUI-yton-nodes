import { api } from "../../../scripts/api.js";
import { button, el, mediaURL, request } from "./replacement_common.js";

export function openReplacementAnchors(owner, config, index, save) {
  const dialog = el("dialog", "yr-anchor-dialog");
  const style = getComputedStyle(owner);
  for (const name of ["--yr-bg", "--yr-fg", "--yr-line", "--yr-field", "--yr-accent"])
    dialog.style.setProperty(name, style.getPropertyValue(name));
  const lifetime = new AbortController();
  const uploading = new Set();
  let closed = false, info, markers = [], frameCallback;
  const screenshots = new Map();
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
  timeline.append(strip, slider, pins);
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
  const persist = () => save(info.key, markers.map(({ frame, image }) => ({ frame, image })));
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
  function renderPins() {
    pins.replaceChildren();
    for (const marker of markers) {
      const pin = button("", () => seek(marker.frame), `跳到第 ${marker.frame + 1} 帧`);
      pin.style.left = `${marker.frame / Math.max(1, info.frames - 1) * 100}%`;
      pin.classList.toggle("ready", Boolean(marker.image));
      pins.append(pin);
    }
    progress.textContent = `${markers.filter(marker => marker.image).length} / ${markers.length} 已上传`;
  }
  function imageCard(image, caption) {
    const card = el("div", "yr-anchor-image");
    if (image) { const img = el("img"); img.src = mediaURL(image); img.alt = caption; card.append(img); }
    card.append(el("span", "", caption));
    return card;
  }
  async function screenshot(frame, card) {
    try {
      if (!screenshots.has(frame)) screenshots.set(frame, request("replacement/anchor-frame", { config, index, frame }));
      const data = await screenshots.get(frame);
      if (closed || !card.isConnected) return;
      const img = el("img"); img.src = mediaURL(data.image); img.alt = `原帧 ${frame + 1}`;
      card.prepend(img);
      const download = el("a", "yr-anchor-download", "↓");
      download.href = mediaURL(data.image); download.download = `片段${index + 1}-第${frame + 1}帧.png`;
      download.title = "下载原帧"; download.setAttribute("aria-label", "下载原帧");
      download.addEventListener("click", event => event.stopPropagation());
      card.append(download);
    } catch (error) { screenshots.delete(frame); if (!closed) status.textContent = error.message; }
  }
  function renderList() {
    list.replaceChildren(); renderPins();
    if (!markers.length) { list.append(el("div", "yr-anchor-empty", "拖动播放头定位画面，按 C 收集需要替换的帧")); return; }
    for (const marker of markers) {
      const row = el("div", "yr-anchor-row"); row.dataset.frame = String(marker.frame);
      const label = button(`第 ${marker.frame + 1} 帧`, () => seek(marker.frame), `定位第 ${marker.frame + 1} 帧`);
      label.classList.add("yr-anchor-frame-label");
      const original = imageCard(null, "原帧");
      original.addEventListener("click", () => seek(marker.frame));
      const replacement = imageCard(marker.image, marker.image ? "替换帧" : "＋ 上传替换帧");
      const file = el("input"); file.type = "file"; file.accept = "image/*"; file.hidden = true;
      file.setAttribute("aria-label", `上传第 ${marker.frame + 1} 帧的替换图片`);
      const uploadButton = button(uploading.has(marker.frame) ? "上传中…" : marker.image ? "更换图片" : "上传图片", () => file.click(), `上传第 ${marker.frame + 1} 帧的替换图片`);
      uploadButton.disabled = uploading.has(marker.frame);
      replacement.addEventListener("click", () => file.click());
      replacement.addEventListener("dragover", event => { event.preventDefault(); replacement.classList.add("drag-over"); });
      replacement.addEventListener("dragleave", () => replacement.classList.remove("drag-over"));
      replacement.addEventListener("drop", event => {
        event.preventDefault(); replacement.classList.remove("drag-over");
        void upload(event.dataTransfer.files[0], marker, uploadButton);
      });
      file.addEventListener("change", () => { void upload(file.files[0], marker, uploadButton); });
      const tools = el("div", "yr-anchor-row-tools");
      tools.append(uploadButton, button("移除", () => { markers = markers.filter(item => item !== marker); persist(); renderList(); }, `移除第 ${marker.frame + 1} 帧`));
      row.append(label, original, el("span", "yr-anchor-arrow", "→"), replacement, tools, file);
      list.append(row); void screenshot(marker.frame, original);
    }
  }
  function collect() {
    if (!info) return;
    video.pause();
    const frame = currentFrame();
    if (!markers.some(marker => marker.frame === frame)) {
      markers.push({ frame, image: "" }); markers.sort((a, b) => a.frame - b.frame);
      persist(); renderList();
    }
    list.querySelector(`[data-frame="${frame}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  async function upload(file, marker, control) {
    if (!file || uploading.has(marker.frame)) return;
    if (!file.type.startsWith("image/")) { status.textContent = "请选择图片文件。"; return; }
    uploading.add(marker.frame);
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
      marker.image = [data.subfolder, data.name].filter(Boolean).join("/"); persist();
    } catch (error) { if (!closed) status.textContent = error.message; }
    finally { uploading.delete(marker.frame); if (!closed) renderList(); }
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
    if (event.target instanceof Element && event.target.closest("input:not([type='range']),textarea,[contenteditable='true']")) return;
    if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key.toLowerCase() === "c") { event.preventDefault(); collect(); }
    else if (event.code === "Space") { event.preventDefault(); void togglePlayback(); }
    else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault(); if (info) seek(currentFrame() + (event.key === "ArrowRight" ? 1 : -1));
    }
  }, { capture: true, signal: lifetime.signal });
  for (const event of ["pointerdown", "keydown", "wheel", "drop", "paste"])
    dialog.addEventListener(event, event => event.stopPropagation());
  dialog.addEventListener("close", () => {
    closed = true; lifetime.abort(); video.pause();
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
    renderList(); sync();
  }).catch(error => { if (!closed) { status.textContent = error.message; counter.textContent = "片段加载失败"; } });
  return { close: () => dialog.close(), onClose: callback => { closeHook = callback; } };
}
