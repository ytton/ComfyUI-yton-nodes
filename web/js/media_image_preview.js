import { imageChannelURL, showMaskPreview } from "./media_mask_preview.js";

export function openImagePreview(url, filename, trigger) {
  const dialog = document.createElement("dialog");
  dialog.className = "yton-image-preview";
  const headingId = `yton-preview-${crypto.randomUUID()}`;
  dialog.setAttribute("aria-labelledby", headingId);

  const header = document.createElement("div");
  header.className = "yton-image-preview-header";
  const heading = document.createElement("div");
  heading.id = headingId;
  heading.className = "yton-image-preview-title";
  heading.textContent = filename.replaceAll("\\", "/").split("/").pop();
  heading.title = filename;
  const size = document.createElement("span");
  size.className = "yton-image-preview-size";
  const close = document.createElement("button");
  close.type = "button";
  close.className = "yton-image-preview-close";
  close.title = "关闭预览";
  close.setAttribute("aria-label", close.title);
  close.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';
  header.append(heading, size, close);

  const body = document.createElement("div");
  body.className = "yton-image-preview-body";
  const image = document.createElement("img");
  image.alt = heading.textContent;
  image.draggable = false;
  const status = document.createElement("span");
  status.className = "yton-image-preview-status";
  status.setAttribute("role", "status");
  status.textContent = "图片加载中…";
  image.onload = () => {
    size.textContent = `${image.naturalWidth} × ${image.naturalHeight}`;
    status.hidden = true;
  };
  image.onerror = () => { status.textContent = "图片加载失败"; };
  image.src = imageChannelURL(url, "rgb");
  const imageFrame = document.createElement("div");
  imageFrame.className = "yton-image-preview-frame";
  imageFrame.append(image);
  showMaskPreview(imageFrame, url);
  body.append(imageFrame, status);
  dialog.append(header, body);

  let disposed = false;
  function dispose() {
    if (disposed) return;
    disposed = true;
    if (dialog.open) dialog.close();
    dialog.remove();
    if (trigger?.isConnected) trigger.focus({ preventScroll: true });
  }
  close.onclick = dispose;
  dialog.addEventListener("close", dispose, { once: true });
  dialog.addEventListener("pointerdown", event => event.stopPropagation());
  dialog.addEventListener("keydown", event => event.stopPropagation());
  dialog.addEventListener("click", event => {
    event.stopPropagation();
    if (event.target === dialog) dispose();
  });
  document.body.append(dialog);
  dialog.showModal();
  close.focus({ preventScroll: true });
  return dispose;
}
