// Adapted from the locally installed PGS editor sources. See docs/CHARACTER_REPLACEMENT.md.

let popoverHideTimer=null;

export function element(tag, className = "", text = undefined) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

export function popover() {
  let current = document.querySelector("#yr-pgs-popover");
  if (!current) {
    current = element("div", "yr-pgs-popover"); current.id = "yr-pgs-popover"; current.hidden = true; document.body.appendChild(current);
    current.addEventListener("mouseenter", () => { if (popoverHideTimer) { clearTimeout(popoverHideTimer); popoverHideTimer = null; } });
    current.addEventListener("mouseleave", () => hidePopover());
  }
  return current;
}

export function hidePopover() {
  if (popoverHideTimer) { clearTimeout(popoverHideTimer); popoverHideTimer = null; }
  const p = popover(); p.hidden = true; p.innerHTML = "";
}

export function schedulePopoverHide() {
  if (popoverHideTimer) clearTimeout(popoverHideTimer);
  popoverHideTimer = setTimeout(() => { popoverHideTimer = null; hidePopover(); }, 220);
}

export function showAssetPopover(asset, anchor) {
  const p = popover(); p.hidden = false; p.innerHTML = "";
  const title = element("div"); title.style.fontWeight = "750"; title.style.marginBottom = "6px"; title.textContent = `@${asset.alias} → ${asset.nativeLabel}`; p.appendChild(title);
  if (asset.previewUrl) {
    const media = asset.kind === "image" ? element("img", "yr-pgs-popover-media") : asset.kind === "video" ? element("video", "yr-pgs-popover-media") : element("audio", "yr-pgs-popover-media");
    media.src = asset.previewUrl; if (asset.kind !== "image") { media.controls = true; media.preload = "metadata"; } else media.alt = `@${asset.alias}`;
    p.appendChild(media);
  } else p.appendChild(element("div", "yr-pgs-preview-text", "当前素材无法生成浏览器预览"));
  const detail = element("div", "yr-pgs-preview-text", `${asset.kind === "image" ? "图片素材" : asset.kind === "video" ? "视频素材" : "音频素材"} · ${asset.scenes || "全部场景"}`); p.appendChild(detail);
  const rect = anchor.getBoundingClientRect(); p.style.left = `${Math.max(12, rect.left)}px`; p.style.top = `${Math.min(window.innerHeight - 200, rect.bottom + 6)}px`;
}

export function resolvePromptAliases(prompt, assets, taskType = "auto") {
  let resolved = String(prompt ?? "");
  const sortedAssets = [...assets].sort((a, b) => (b.alias?.length || 0) - (a.alias?.length || 0));

  if (taskType === "FL2VA") {
    const pictureAssets = sortedAssets.filter(a => a.kind === "image");
    pictureAssets.sort((a, b) => {
      const numA = parseInt(a.nativeLabel?.match(/\d+/)?.[0] || "0");
      const numB = parseInt(b.nativeLabel?.match(/\d+/)?.[0] || "0");
      return numA - numB;
    });
    for (let i = 0; i < pictureAssets.length; i++) {
      const asset = pictureAssets[i];
      const bareLabel = `Picture ${i + 1}`;
      const alias = asset.alias.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`@${alias}(?![A-Za-z0-9_-])`, 'g');
      resolved = resolved.replace(regex, bareLabel);
      const fullWidthRegex = new RegExp(`＠${alias}(?![A-Za-z0-9_-])`, 'g');
      resolved = resolved.replace(fullWidthRegex, bareLabel);
    }
  } else {
    for (const asset of sortedAssets) {
      if (!asset.alias) continue;
      const alias = asset.alias.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`@${alias}(?![A-Za-z0-9_-])`, 'g');
      resolved = resolved.replace(regex, asset.nativeLabel);
      const fullWidthRegex = new RegExp(`＠${alias}(?![A-Za-z0-9_-])`, 'g');
      resolved = resolved.replace(fullWidthRegex, asset.nativeLabel);
    }
  }
  return resolved;
}

export function resolveNativeLabelsToAliases(prompt, assets, taskType = "auto") {
  let resolved = String(prompt ?? "");
  const sortedAssets = [...assets].sort((a, b) => (b.nativeLabel?.length || 0) - (a.nativeLabel?.length || 0));

  if (taskType === "FL2VA") {
    for (const asset of sortedAssets) {
      if (!asset.nativeLabel) continue;
      const match = asset.nativeLabel.match(/^<Picture (\d+)>$/);
      if (match) {
        const bareLabel = `Picture ${match[1]}`;
        const escapedBare = bareLabel.replace(/\s+/g, '\\s+');
        const regex = new RegExp(`\\b${escapedBare}\\b`, 'gi');
        resolved = resolved.replace(regex, `@${asset.alias}`);
      }
    }
    for (const asset of sortedAssets) {
      if (!asset.nativeLabel) continue;
      const escaped = asset.nativeLabel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(escaped, 'g');
      resolved = resolved.replace(regex, `@${asset.alias}`);
    }
  } else {
    for (const asset of sortedAssets) {
      if (!asset.nativeLabel) continue;
      const escaped = asset.nativeLabel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(escaped, 'gi');
      resolved = resolved.replace(regex, `@${asset.alias}`);
    }
  }
  return resolved;
}

export function injectStyles() {
  if(document.getElementById("yton-yr-pgs-prompt-style")) return;
  const style=document.createElement("style");style.id="yton-yr-pgs-prompt-style";
  style.textContent=`    .yr-pgs-preview-text { color:#a8b3c7; white-space:pre-wrap; overflow-wrap:anywhere; }
    .yr-pgs-popover { position:fixed; z-index:100000; width:min(360px,calc(100vw - 24px)); padding:9px; border:1px solid #60718c; border-radius:9px; background:#171a20; color:#eef2f8; box-shadow:0 14px 38px #000c; }
    .yr-pgs-popover[hidden] { display:none; }
    .yr-pgs-popover-media { display:block; width:100%; max-height:240px; object-fit:contain; border-radius:6px; background:#08090c; }
    .yr-pgs-rich-editor { min-height:280px; max-height:420px; overflow-y:auto; padding:8px; border:1px solid #4a5568; border-radius:5px; background:#14171c; color:#eef1f7; outline:none; white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.55; font:inherit; cursor:text; }
    .yr-pgs-rich-editor:focus { border-color:#8eb5ff; }
    .yr-pgs-rich-editor-disabled { cursor:default; opacity:.6; }
    .yr-pgs-token { display:inline-flex; align-items:center; gap:3px; padding:1px 5px 1px 3px; border:1px solid currentColor; border-radius:5px; line-height:1.25; cursor:pointer; user-select:all; margin:0 1px; vertical-align:1px; }
    .yr-pgs-token-image { color:#76c7ff; background:rgba(55,145,205,.14); }
    .yr-pgs-token-video { color:#c7a0ff; background:rgba(133,82,195,.15); }
    .yr-pgs-token-audio { color:#ffbd72; background:rgba(205,124,45,.14); }
    .yr-pgs-token-subject { color:#8ed7a4; background:rgba(64,155,92,.14); }
    .yr-pgs-token-dialogue { color:#ff9fc7; background:rgba(190,63,119,.13); }
    .yr-pgs-token-unknown { color:#ff9999; border-style:dashed; background:rgba(185,56,56,.12); }
    .yr-pgs-token-dot { display:inline-block; width:7px; height:7px; border-radius:50%; background:currentColor; flex:0 0 auto; }
    .yr-pgs-token-label { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .yr-pgs-alias-menu { display:none; position:fixed; z-index:1000; max-height:260px; overflow:auto; padding:6px; border:1px solid #5b6676; border-radius:6px; background:#1d2026; box-shadow:0 12px 32px #000a; }
    .yr-pgs-alias-menu.open { display:block; }
    .yr-pgs-alias-item { display:flex; align-items:center; gap:6px; padding:5px 7px; border-radius:4px; cursor:pointer; color:#dce3f2; }
    .yr-pgs-alias-item:hover { background:#2d3440; }
    .yr-pgs-alias-item-active { background:#2d3440; border:1px solid #8eb5ff; border-radius:4px; }`;
  document.head.append(style);
}
