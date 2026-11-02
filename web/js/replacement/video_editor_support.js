// Adapted from the locally installed PGS editor sources. See docs/CHARACTER_REPLACEMENT.md.

export const H3_FPS=24;

export function setWidgetValue(node, name, value, silent = false, force = false) {
    const w = node.widgets?.find(w => w.name === name);
    if (!w) return;
    if (!force && w.value === value) return;
    w.value = value;
    w.callback?.(value);
    node.properties = node.properties || {};
    node.properties[name] = value;
    if (!silent) {
        node.setDirtyCanvas(true, true);
        node.graph?.setDirtyCanvas(true, true);
    }
}

export function widgetValue(node, name, fb = null) {
    const w = node.widgets?.find(w => w.name === name);
    if (w && w.value !== undefined && w.value !== "") return w.value;
    if (node.properties?.[name] !== undefined && node.properties[name] !== "") return node.properties[name];
    return fb;
}

export function fmt(s) {
    s = Math.max(0, s || 0);
    const h = Math.floor(s / 3600),
        m = Math.floor(s % 3600 / 60),
        x = Math.floor(s % 60);
    return h > 0
        ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`
        : `${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`;
}

export function recommendSegmentSeconds(totalFrames, fps = H3_FPS) {
    if (!totalFrames) return 5;
    const sec = (totalFrames / fps) / 10;
    return Math.max(2, Math.min(20, Math.round(sec * 10) / 10));
}

export function fileUrl(name) {
  const clean=String(name || '').replace(/\s*\[(input|output|temp)\]$/, '').replaceAll('\\','/');
  const type=String(name).match(/\[(input|output|temp)\]$/)?.[1] || 'input';
  const split=clean.lastIndexOf('/');
  return '/view?'+new URLSearchParams({filename:clean.slice(split+1),subfolder:clean.slice(0,Math.max(0,split)),type});
}

export function injectStyles() {
  if(document.getElementById("yton-pgs-video-style")) return;
  const style=document.createElement("style");style.id="yton-pgs-video-style";
  style.textContent=`.yr-pgs-ov{position:fixed;inset:0;z-index:10500;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.8);font:12px Arial,sans-serif}
.yr-pgs-dl{width:min(920px,calc(100vw - 40px));max-height:90vh;overflow-y:auto;background:#1a222b;color:#d7e3ec;border:1px solid #365161;border-radius:10px;padding:20px;box-shadow:0 20px 60px rgba(0,0,0,.7)}
.yr-pgs-tb2{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #365161}
.yr-pgs-tb2 button,.yr-pgs-tb2 input,.yr-pgs-tb2 select{background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:4px 8px;font-size:11px;cursor:pointer}
.yr-pgs-tb2 button.on{background:#0aa4d6;color:#06131b;border-color:#0aa4d6;font-weight:bold}
.yr-pgs-pv{position:relative;width:100%;aspect-ratio:16/9;background:#000;border-radius:6px;overflow:hidden;margin-bottom:10px}
.yr-pgs-pv video{width:100%;height:100%;object-fit:contain;outline:none}
.yr-pgs-cb{position:absolute;border:2px dashed #38bdf8;display:none;cursor:move;box-sizing:border-box;box-shadow:0 0 0 9999px rgba(0,0,0,.5);z-index:10}
.yr-pgs-ch{position:absolute;width:20px;height:20px;background:transparent}
.yr-pgs-tl{display:flex;flex-direction:column;gap:4px;background:rgba(0,0,0,.35);padding:8px;border-radius:4px;margin-bottom:8px}
.yr-pgs-tr{position:relative;height:18px;font-size:10px;color:#aaa;user-select:none}
.yr-pgs-ts{position:relative;width:100%;height:22px;background:#111;border-radius:4px;cursor:pointer;box-shadow:inset 0 1px 3px rgba(0,0,0,.5)}
.yr-pgs-tf{position:absolute;height:100%;background:rgba(14,165,233,.35)}
.yr-pgs-th{position:absolute;top:0;width:8px;height:100%;background:#38bdf8;transform:translateX(-50%);border-radius:2px}
.yr-pgs-pr{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin-bottom:10px}
.yr-pgs-pr label{display:flex;align-items:center;gap:5px;font-size:11px;color:#b8d2dc}
.yr-pgs-pr input,.yr-pgs-pr select{background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:3px 6px;font-size:11px;width:70px}
.yr-pgs-range{position:absolute;bottom:0;left:0;height:4px;background:rgba(0,255,0,0.8);pointer-events:none;z-index:8;transition:left .1s,width .1s}
.yr-pgs-seg-item{border:1px solid #3a5363;border-radius:4px;background:#223744;color:#dce7ee;padding:4px 6px;font-size:10px;cursor:pointer;text-align:left;}
.yr-pgs-seg-item:hover{background:#2a4a58;}
.yr-pgs-seg-item b{color:#0aa4d6;}`;
  document.head.append(style);
}
