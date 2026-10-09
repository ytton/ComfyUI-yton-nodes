export function imageChannelURL(url, channel) {
  const parsed = new URL(url, window.location.href);
  parsed.searchParams.set("channel", channel);
  return parsed.href;
}

// ComfyUI stores editable pixels as transparent alpha. Keep RGB visible and
// draw the inverted alpha as a fluorescent overlay only in the preview.
export function showMaskPreview(container, url) {
  const alpha = new Image();
  alpha.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.className = "yton-image-mask-preview";
    canvas.setAttribute("aria-hidden", "true");
    const scale = Math.min(1, 1024 / Math.max(alpha.naturalWidth, alpha.naturalHeight));
    canvas.width = Math.max(1, Math.round(alpha.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(alpha.naturalHeight * scale));
    const context = canvas.getContext("2d");
    context.drawImage(alpha, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    let painted = false;
    for (let i = 0; i < pixels.data.length; i += 4) {
      const mask = 255 - pixels.data[i + 3];
      if (mask) painted = true;
      pixels.data[i] = 57;
      pixels.data[i + 1] = 255;
      pixels.data[i + 2] = 116;
      pixels.data[i + 3] = Math.round(mask * .4);
    }
    if (!painted) return;
    context.putImageData(pixels, 0, 0);
    container.append(canvas);
  };
  alpha.src = imageChannelURL(url, "a");
}
