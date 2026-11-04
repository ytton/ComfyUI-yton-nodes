// Adapted from the locally installed PGS editor sources. See docs/CHARACTER_REPLACEMENT.md.
// video_editor.mjs - 视频编辑器

import { widgetValue, setWidgetValue, fileUrl, fmt,
         recommendSegmentSeconds, H3_FPS } from './video_editor_support.js';
import { createShotControls, requestShotPlan } from './shot_planner.js';

let currentVideoEditor = null;

const SEG_LEN_FREE = [0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 15, 20, 30, 60];
const SEG_LEN_H3 = [22, 39, 56, 73, 90, 107, 124, 141, 158, 175, 192,
                    209, 226, 243, 260, 277, 294, 311, 328, 345, 362,
                    379, 396, 413, 430, 447, 464, 481, 498, 515, 532];

const CTX_FREE = [0, 6, 12, 18, 22, 24, 30, 36, 39, 48, 56, 60, 72, 96, 120];
const CTX_H3 = [0, 5, 22, 39, 56];

const COMMON_ASPECTS = [
    [1, 1], [5, 4], [4, 3], [3, 2], [16, 10], [16, 9], [21, 9],
    [4, 5], [3, 4], [2, 3], [10, 16], [9, 16], [9, 21]
];

function nearestInList(value, list) {
    value = Number(value) || 0;
    let best = list[0], bestDist = Math.abs(list[0] - value);
    for (const v of list) {
        const d = Math.abs(v - value);
        if (d < bestDist) { best = v; bestDist = d; }
    }
    return best;
}

function gcd(a, b) { return b ? gcd(b, a % b) : a; }

function matchAspect(w, h) {
    if (!w || !h) return "?";
    const actual = w / h;
    let best = null, bestDiff = Infinity;
    for (const [aw, ah] of COMMON_ASPECTS) {
        const diff = Math.abs(actual - aw / ah) / (aw / ah);
        if (diff < bestDiff) {
            bestDiff = diff;
            best = [aw, ah];
        }
    }
    if (best && bestDiff <= 0.02) return `${best[0]}:${best[1]}`;
    const rw = Math.round(w);
    const rh = Math.round(h);
    const div = gcd(rw, rh);
    const fw = rw / div;
    const fh = rh / div;
    if (fw <= 100 && fh <= 100) return `${fw}:${fh}`;
    return `${actual.toFixed(2)}:1`;
}

export function openVideoEditor(node) {
    if (currentVideoEditor) {
        currentVideoEditor.remove();
        currentVideoEditor = null;
    }
    const ov = document.createElement("div");
    ov.className = "yr-pgs-ov";
    currentVideoEditor = ov;
    document.body.appendChild(ov);
    const dl = document.createElement("div");
    dl.className = "yr-pgs-dl";
    ov.appendChild(dl);

    const titleBar = document.createElement("div");
    titleBar.style.cssText = "display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap;";
    const titleText = document.createElement("div");
    titleText.style.cssText = "font-size:16px;font-weight:bold;";
    titleText.textContent = "视频编辑器";
    const aspectInfo = document.createElement("span");
    aspectInfo.style.cssText = "font-size:11px;padding:3px 10px;background:#0d1c24;border:1px solid #3a5363;border-radius:4px;white-space:nowrap;display:none;";
    titleBar.appendChild(titleText);
    titleBar.appendChild(aspectInfo);
    dl.appendChild(titleBar);

    const pv = document.createElement("div");
    pv.className = "yr-pgs-pv";
    const ve = document.createElement("video");
    ve.src = fileUrl(widgetValue(node, "filename", ""));
    ve.controls = true;
    ve.muted = false;
    pv.appendChild(ve);
    dl.appendChild(pv);

    const rangeOverlay = document.createElement("div");
    rangeOverlay.className = "yr-pgs-range";
    pv.appendChild(rangeOverlay);

    const cb = document.createElement("div");
    cb.className = "yr-pgs-cb";
    cb.style.display = "none";
    const hs = {
        tl: "top:-3px;left:-3px;cursor:nwse-resize;border-top:6px solid #38bdf8;border-left:6px solid #38bdf8",
        tr: "top:-3px;right:-3px;cursor:nesw-resize;border-top:6px solid #38bdf8;border-right:6px solid #38bdf8",
        bl: "bottom:-3px;left:-3px;cursor:nesw-resize;border-bottom:6px solid #38bdf8;border-left:6px solid #38bdf8",
        br: "bottom:-3px;right:-3px;cursor:nwse-resize;border-bottom:6px solid #38bdf8;border-right:6px solid #38bdf8",
        tm: "top:-3px;left:50%;transform:translateX(-50%);cursor:ns-resize;border-top:6px solid #38bdf8;width:16px;height:10px",
        bm: "bottom:-3px;left:50%;transform:translateX(-50%);cursor:ns-resize;border-bottom:6px solid #38bdf8;width:16px;height:10px",
        lm: "top:50%;left:-3px;transform:translateY(-50%);cursor:ew-resize;border-left:6px solid #38bdf8;width:10px;height:16px",
        rm: "top:50%;right:-3px;transform:translateY(-50%);cursor:ew-resize;border-right:6px solid #38bdf8;width:10px;height:16px"
    };
    Object.entries(hs).forEach(([n, c]) => {
        const h = document.createElement("div");
        h.className = "yr-pgs-ch";
        h.style.cssText = c;
        h.dataset.h = n;
        cb.appendChild(h);
    });
    pv.appendChild(cb);

    const tl = document.createElement("div");
    tl.className = "yr-pgs-tl";
    const tr = document.createElement("div");
    tr.className = "yr-pgs-tr";
    const ts = document.createElement("div");
    ts.className = "yr-pgs-ts";
    const segOverlay = document.createElement("div");
    segOverlay.style.cssText = "position:absolute;inset:0;pointer-events:none;overflow:hidden;border-radius:4px;z-index:1;";
    const tf = document.createElement("div");
    tf.className = "yr-pgs-tf";
    const sh = document.createElement("div");
    sh.className = "yr-pgs-th";
    const eh = document.createElement("div");
    eh.className = "yr-pgs-th";
    ts.append(segOverlay, tf, sh, eh);
    tl.append(tr, ts);
    dl.appendChild(tl);

    const timeRow = document.createElement("div");
    timeRow.style.cssText = "display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;";
    dl.appendChild(timeRow);

    function createTimeInput(labelPrefix) {
        const container = document.createElement("div");
        container.style.cssText = "display:flex;align-items:center;gap:5px;";
        const lb = document.createElement("label");
        lb.textContent = labelPrefix + ":";
        lb.style.cssText = "font-size:11px;color:#b8d2dc;white-space:nowrap;";
        const inp = document.createElement("input");
        inp.type = "number";
        inp.step = 0.01;
        inp.style.cssText = "width:70px;background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:3px 6px;font-size:11px;";
        container.appendChild(lb);
        container.appendChild(inp);
        return { container, lb, inp };
    }

    const startTI = createTimeInput("开始");
    startTI.container.style.justifyContent = "flex-start";
    timeRow.appendChild(startTI.container);

    const centerContainer = document.createElement("div");
    centerContainer.style.cssText = "flex:1;display:flex;align-items:center;justify-content:center;gap:8px;";
    timeRow.appendChild(centerContainer);

    const durTI = createTimeInput("时长");
    centerContainer.appendChild(durTI.container);

    let loop = true;
    const loopBtn = document.createElement("button");
    loopBtn.textContent = "循环: 开";
    loopBtn.classList.add("on");
    loopBtn.style.cssText = "border:1px solid #3a5363;border-radius:4px;background:#0aa4d6;color:#06131b;cursor:pointer;font-size:11px;padding:3px 8px;";
    loopBtn.onclick = () => {
        loop = !loop;
        loopBtn.textContent = loop ? "循环: 开" : "循环: 关";
        loopBtn.classList.toggle("on", loop);
        loopBtn.style.background = loop ? "#0aa4d6" : "#223744";
        loopBtn.style.color = loop ? "#06131b" : "#dce7ee";
    };
    centerContainer.appendChild(loopBtn);

    const endTI = createTimeInput("结束");
    endTI.container.style.justifyContent = "flex-end";
    timeRow.appendChild(endTI.container);

    const tb = document.createElement("div");
    tb.className = "yr-pgs-tb2";
    let cropOn = false,
        mode = widgetValue(node, "display_mode", "seconds");
    let dur = 0,
        drg = null,
        off = 0,
        selW = 0,
        cdrg = null,
        csx = 0,
        csy = 0,
        ccx = 0,
        ccy = 0,
        ccw = 1,
        cch = 1;
    let keepAspect = true;
    let videoAspectRatio = 1.0;

    const mb = document.createElement("button");
    mb.textContent = "帧模式";
    mb.onclick = () => {
        const fr = parseFloat(fri.value) || 24;
        let s, e;
        if (mode === "seconds") {
            s = parseFloat(widgetValue(node, "start_time", 0)) || 0;
            e = parseFloat(widgetValue(node, "end_time", 0)) || dur || 0;
            if (e <= s) e = s + (parseFloat(widgetValue(node, "duration", 0)) || 0);
        } else {
            const sf = parseInt(widgetValue(node, "start_frame", 0)) || 0;
            const ef = parseInt(widgetValue(node, "end_frame", 0)) || 0;
            const df = parseInt(widgetValue(node, "duration_frames", 0)) || 0;
            s = sf / fr;
            e = ef > sf ? ef / fr : (sf + df) / fr;
            if (e <= s) e = s + df / fr;
        }
        const d = Math.max(0, e - s);
        mode = mode === "seconds" ? "frames" : "seconds";
        mb.textContent = mode === "seconds" ? "帧模式" : "秒模式";
        setWidgetValue(node, "display_mode", mode);
        setWidgetValue(node, "start_time", s);
        setWidgetValue(node, "end_time", e);
        setWidgetValue(node, "duration", d);
        setWidgetValue(node, "start_frame", Math.round(s * fr));
        setWidgetValue(node, "end_frame", Math.round(e * fr));
        setWidgetValue(node, "duration_frames", Math.round(d * fr));
        node.properties = node.properties || {};
        node.properties["duration_seconds"] = d;
        updateTS();
        updateTimeInputs();
        updateParams();
        updateRangeOverlay();
        if (segEnabled) {
            rebuildSegLenOptions();
            rebuildCtxOptions();
            recalcSegments();
        }
    };
    tb.appendChild(mb);

    const frl = document.createElement("span");
    frl.textContent = "帧率:";
    frl.style.cssText = "font-size:11px;color:#b8d2dc;margin-left:8px;";
    tb.appendChild(frl);

    const fri = document.createElement("input");
    fri.type = "number";
    fri.value = widgetValue(node, "frame_rate", 24);
    fri.min = 1;
    fri.max = 120;
    fri.style.cssText = "width:60px;background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:3px 6px;font-size:11px;";
    fri.onchange = () => {
        setWidgetValue(node, "frame_rate", parseFloat(fri.value) || 24);
        syncT();
        updateTS();
        updateTimeInputs();
        updateParams();
        if (segEnabled) recalcSegments();
    };
    tb.appendChild(fri);

    dl.appendChild(tb);

    const commonParams = document.createElement("div");
    commonParams.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:10px;";
    dl.appendChild(commonParams);
    const compressionLabel = document.createElement("span");
    compressionLabel.textContent = "参考视频压缩";
    commonParams.appendChild(compressionLabel);

    const resetBtn = document.createElement("button");
    resetBtn.textContent = "重置";
    resetBtn.title = "恢复原始尺寸";
    resetBtn.style.cssText = "border:1px solid #3a5363;border-radius:4px;background:#223744;color:#dce7ee;cursor:pointer;font-size:11px;padding:3px 8px;";
    resetBtn.onclick = () => {
        setWidgetValue(node, "custom_width", 0);
        setWidgetValue(node, "custom_height", 0);
        if (ve.videoWidth && ve.videoHeight) {
            widthInput.value = ve.videoWidth;
            widthInput.placeholder = `原始 ${ve.videoWidth}`;
            heightInput.value = ve.videoHeight;
            heightInput.placeholder = `原始 ${ve.videoHeight}`;
        } else {
            widthInput.value = 0;
            heightInput.value = 0;
        }
        updateParams();
    };
    commonParams.appendChild(resetBtn);

    const widthLabel = document.createElement("label");
    widthLabel.textContent = "宽:";
    commonParams.appendChild(widthLabel);

    const widthInput = document.createElement("input");
    widthInput.type = "number";
    widthInput.setAttribute("aria-label", "参考视频压缩宽度");
    widthInput.title = "只调整参考视频，不影响节点的生成目标宽度。";
    widthInput.step = 8;
    widthInput.value = widgetValue(node, "custom_width", 0);
    widthInput.style.cssText = "width:70px;background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:3px 6px;font-size:11px;";
    commonParams.appendChild(widthInput);

    const aspectBtn = document.createElement("button");
    aspectBtn.textContent = "🔗";
    aspectBtn.title = "等比锁定";
    aspectBtn.className = "yr-pgs-aspect-btn" + (keepAspect ? " on" : "");
    aspectBtn.style.cssText = "border:1px solid #3a5363;border-radius:4px;background:#0aa4d6;color:#06131b;cursor:pointer;font-size:12px;padding:2px 6px;";
    aspectBtn.onclick = () => {
        keepAspect = !keepAspect;
        aspectBtn.classList.toggle("on", keepAspect);
        aspectBtn.style.background = keepAspect ? "#0aa4d6" : "#223744";
        aspectBtn.style.color = keepAspect ? "#06131b" : "#dce7ee";
    };
    commonParams.appendChild(aspectBtn);

    const heightLabel = document.createElement("label");
    heightLabel.textContent = "高:";
    commonParams.appendChild(heightLabel);

    const heightInput = document.createElement("input");
    heightInput.type = "number";
    heightInput.setAttribute("aria-label", "参考视频压缩高度");
    heightInput.title = "只调整参考视频，不影响节点的生成目标高度。";
    heightInput.step = 8;
    heightInput.value = widgetValue(node, "custom_height", 0);
    heightInput.style.cssText = "width:70px;background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:3px 6px;font-size:11px;";
    commonParams.appendChild(heightInput);

    const rl = document.createElement("label");
    rl.textContent = "缩放:";
    commonParams.appendChild(rl);

    const rs = document.createElement("select");
    rs.innerHTML = `<option value="maintain aspect ratio">保持比例</option><option value="stretch to fit">拉伸</option><option value="pad">填充</option><option value="crop">裁剪</option>`;
    rs.value = widgetValue(node, "resize_method", "maintain aspect ratio");
    rs.onchange = () => {
        setWidgetValue(node, "resize_method", rs.value);
        updateAspectInfo();
    };
    commonParams.appendChild(rs);

    const cropBtnRow = document.createElement("div");
    cropBtnRow.style.cssText = "border-top:1px solid #365161; padding-top:12px; margin-top:24px; margin-bottom:8px;";
    dl.appendChild(cropBtnRow);

    const cbtn = document.createElement("button");
    cbtn.textContent = "Crop";
    cbtn.style.cssText = "border:1px solid #3a5363;border-radius:4px;background:#223744;color:#dce7ee;cursor:pointer;font-size:11px;padding:4px 12px;";
    cbtn.onclick = () => {
        cropOn = !cropOn;
        cbtn.classList.toggle("on", cropOn);
        cb.style.display = cropOn ? "block" : "none";
        ve.controls = !cropOn;
        cropSection.style.display = cropOn ? "block" : "none";
        if (cropOn) {
            cbtn.style.background = "#0aa4d6";
            cbtn.style.color = "#06131b";
            ve.pause();
            updateCb();
            updateCropPixelInputs();
        } else {
            cbtn.style.background = "#223744";
            cbtn.style.color = "#dce7ee";
        }
        updateParams();
    };
    cropBtnRow.appendChild(cbtn);

    const cropSection = document.createElement("div");
    cropSection.style.cssText = "display:none; padding-top:8px; margin-top:4px;";
    dl.appendChild(cropSection);

    // ★ 单行布局：比例 + 位置 + 大小
    const cropRow = document.createElement("div");
    cropRow.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:10px;";
    cropSection.appendChild(cropRow);

    // 比例
    const ratioLabel = document.createElement("span");
    ratioLabel.textContent = "比例：";
    ratioLabel.style.cssText = "font-size:12px;color:#b8d2dc;";
    cropRow.appendChild(ratioLabel);

    const ratioSelect = document.createElement("select");
    ratioSelect.style.cssText = "background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:3px 6px;font-size:11px;cursor:pointer;";
    ratioSelect.innerHTML = `
        <option value="free">自由</option>
        <option value="original">原始</option>
        <option value="1:1">1:1</option>
        <option value="4:5">4:5</option>
        <option value="5:4">5:4</option>
        <option value="16:9">16:9</option>
        <option value="9:16">9:16</option>
        <option value="4:3">4:3</option>
        <option value="3:4">3:4</option>
        <option value="3:2">3:2</option>
        <option value="2:3">2:3</option>
        <option value="2:1">2:1</option>
        <option value="1:2">1:2</option>
    `;
    cropRow.appendChild(ratioSelect);

    // 位置
    const posLabel = document.createElement("span");
    posLabel.textContent = "位置：";
    posLabel.style.cssText = "font-size:12px;color:#b8d2dc;";
    cropRow.appendChild(posLabel);

    function createPixelInput(label, nodeName, container, width = 60) {
        const lb = document.createElement("label");
        lb.style.cssText = "display:inline-flex;align-items:center;gap:3px;font-size:11px;color:#b8d2dc;";
        lb.textContent = label + ":";
        const inp = document.createElement("input");
        inp.type = "number";
        inp.step = 1;
        inp.min = 0;
        inp.style.cssText = `width:${width}px;background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:3px 6px;font-size:11px;`;
        container.appendChild(lb);
        lb.appendChild(inp);
        return { lb, inp };
    }
    const cropXInput = createPixelInput("X", "crop_x", cropRow);
    const cropYInput = createPixelInput("Y", "crop_y", cropRow);

    // 大小
    const sizeLabel = document.createElement("span");
    sizeLabel.textContent = "大小：";
    sizeLabel.style.cssText = "font-size:12px;color:#b8d2dc;";
    cropRow.appendChild(sizeLabel);

    const cropWInput = createPixelInput("宽", "crop_w", cropRow);
    const cropHInput = createPixelInput("高", "crop_h", cropRow);

    // ========== 分段规划面板 ==========
    let segPlan = null;
    let segEnabled = false;
    let segPanelInited = false;
    let segmentRevision = 0;

    const segPanel = document.createElement("div");
    segPanel.style.cssText = "border-top:1px solid #365161;padding-top:10px;margin-top:12px;display:none;";
    dl.appendChild(segPanel);

    // 头部：只有按钮（标题合并进按钮）
    const segHeader = document.createElement("div");
    segHeader.style.cssText = "display:flex;align-items:center;gap:10px;margin-bottom:8px;";
    segPanel.appendChild(segHeader);

    // ★ 分段规划按钮（也是启用开关）
    const segToggleBtn = document.createElement("button");
    segToggleBtn.textContent = "分段规划";
    segToggleBtn.style.cssText = "border:1px solid #3a5363;border-radius:4px;background:#223744;color:#b8d2dc;cursor:pointer;font-size:12px;font-weight:bold;padding:4px 14px;transition:all .15s;";
    segHeader.appendChild(segToggleBtn);

    // 参数行
    const segParamsRow = document.createElement("div");
    segParamsRow.style.cssText = "display:none;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:8px;";
    segPanel.appendChild(segParamsRow);

    // ★ 模式（挪到最前）
    const segPresetLb = document.createElement("span");
    segPresetLb.textContent = "模式:";
    segPresetLb.style.cssText = "font-size:11px;color:#b8d2dc;";
    segParamsRow.appendChild(segPresetLb);

    const segPresetSel = document.createElement("select");
    segPresetSel.style.cssText = "background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:3px 6px;font-size:11px;cursor:pointer;min-width:100px;";
    segPresetSel.innerHTML = `
        <option value="none">自由</option>
        <option value="minimaxh3">MiniMax H3</option>
    `;
    segPresetSel.value = "none";
    segParamsRow.appendChild(segPresetSel);

    // 段长
    const segLenLb = document.createElement("label");
    segLenLb.textContent = "段长(总长):";
    segLenLb.style.cssText = "font-size:11px;color:#b8d2dc;";
    segParamsRow.appendChild(segLenLb);
    const segLenSel = document.createElement("select");
    segLenSel.style.cssText = "background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:3px 6px;font-size:11px;cursor:pointer;min-width:150px;";
    segParamsRow.appendChild(segLenSel);

    // 重叠
    const segCtxLb = document.createElement("label");
    segCtxLb.textContent = "重叠:";
    segCtxLb.style.cssText = "font-size:11px;color:#b8d2dc;";
    segParamsRow.appendChild(segCtxLb);
    const segCtxSel = document.createElement("select");
    segCtxSel.style.cssText = "background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:3px 6px;font-size:11px;cursor:pointer;min-width:130px;";
    segParamsRow.appendChild(segCtxSel);

    // 输出
    const segModeLb = document.createElement("label");
    segModeLb.textContent = "输出:";
    segModeLb.style.cssText = "font-size:11px;color:#b8d2dc;";
    segParamsRow.appendChild(segModeLb);
    const segModeSel = document.createElement("select");
    segModeSel.style.cssText = "background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:3px 6px;font-size:11px;";
    segModeSel.innerHTML = `<option value="raw">含上下文</option><option value="delivered">仅新增帧</option>`;
    segParamsRow.appendChild(segModeSel);

    const shotControls = createShotControls(segParamsRow, () => { if (segEnabled) void recalcSegments(); });

    const segStatus = document.createElement("div");
    segStatus.style.cssText = "font-size:11px;color:#0aa4d6;margin-bottom:8px;padding:4px 8px;background:#0d1c24;border-radius:4px;display:none;";
    segPanel.appendChild(segStatus);

    const segList = document.createElement("div");
    segList.style.cssText = "display:none;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px;max-height:200px;overflow-y:auto;";
    segPanel.appendChild(segList);

    function rebuildSegLenOptions(preferSeconds) {
        const isH3 = segPresetSel.value === "minimaxh3";
        const showFrames = (mode === "frames");
        const oldSec = preferSeconds !== undefined
            ? Number(preferSeconds)
            : (parseFloat(segLenSel.value) || 5);

        segLenSel.innerHTML = "";
        if (isH3) {
            const targetFrames = oldSec * H3_FPS;
            const chosen = nearestInList(targetFrames, SEG_LEN_H3);
            SEG_LEN_H3.forEach(f => {
                const sec = f / H3_FPS;
                const o = document.createElement("option");
                o.value = sec.toFixed(4);
                o.textContent = showFrames ? `${f} 帧` : `${f} 帧 (${sec.toFixed(2)}s)`;
                segLenSel.appendChild(o);
            });
            segLenSel.value = (chosen / H3_FPS).toFixed(4);
        } else {
            const chosen = nearestInList(oldSec, SEG_LEN_FREE);
            SEG_LEN_FREE.forEach(s => {
                const o = document.createElement("option");
                o.value = s;
                const frames = Math.round(s * H3_FPS);
                o.textContent = showFrames ? `${frames} 帧` : `${s} 秒`;
                segLenSel.appendChild(o);
            });
            segLenSel.value = chosen;
        }
    }

    function rebuildCtxOptions(preferFrames) {
        const isH3 = segPresetSel.value === "minimaxh3";
        const showFrames = (mode === "frames");
        const list = isH3 ? CTX_H3 : CTX_FREE;
        const oldFrames = preferFrames !== undefined
            ? Number(preferFrames)
            : (parseInt(segCtxSel.value) || 0);
        const chosen = nearestInList(oldFrames, list);

        segCtxSel.innerHTML = "";
        list.forEach(f => {
            const o = document.createElement("option");
            o.value = f;
            if (f === 0) {
                o.textContent = "0 (无重叠)";
            } else if (showFrames) {
                o.textContent = `${f} 帧`;
            } else {
                o.textContent = `${f} 帧 (≈${(f / H3_FPS).toFixed(2)}s)`;
            }
            segCtxSel.appendChild(o);
        });
        segCtxSel.value = chosen;
    }

    function renderSegmentBars() {
        segOverlay.innerHTML = "";
        if (!segEnabled || !segPlan || !dur) return;
        const totalFrames = Math.round(dur * H3_FPS);
        segPlan.segments.forEach((s, i) => {
            if (s.end <= s.start) return;
            const bar = document.createElement("div");
            const hue = (i * 137.508) % 360;
            const leftPct = (s.start / totalFrames) * 100;
            const widthPct = ((s.end - s.start) / totalFrames) * 100;
            bar.style.cssText =
                "position:absolute;top:0;height:100%;box-sizing:border-box;" +
                `left:${leftPct}%;width:${widthPct}%;` +
                `background:hsla(${hue},70%,55%,0.5);` +
                `border-right:1px solid hsla(${hue},80%,70%,0.95);`;
            segOverlay.appendChild(bar);
        });
    }

    async function recalcSegments() {
        const revision = ++segmentRevision;
        if (!dur) return;
        svb.disabled = false;
        const rawLenSec = parseFloat(segLenSel.value) || 5;
        const ctx = parseInt(segCtxSel.value) || 0;
        const strictH3 = segPresetSel.value === "minimaxh3";
        const outMode = segModeSel.value;
        const showFrames = (mode === "frames");

        const rangeStartFrame = Math.max(0, Math.round(gs() * H3_FPS));
        const rangeEndFrame = Math.max(0, Math.round(ge() * H3_FPS));
        const rangeFrames = rangeEndFrame - rangeStartFrame;

        if (rangeFrames <= 0) {
            segStatus.textContent = "请先在时间线上选择有效范围（开始 < 结束）";
            segList.innerHTML = "";
            segPlan = null;
            segOverlay.innerHTML = "";
            return;
        }

        let raw;
        if (strictH3) {
            const targetFrames = Math.max(5, Math.round(rawLenSec * H3_FPS));
            const legal = [];
            const hi = Math.max(targetFrames + 100, rangeFrames + 100);
            for (let f = 5; f <= hi; f++) {
                if ((f - 5) % 17 === 0) legal.push(f);
            }
            raw = nearestInList(targetFrames, legal);
        } else {
            raw = Math.max(1, Math.round(rawLenSec * H3_FPS));
        }
        if (raw > rangeFrames) raw = rangeFrames;

        let step;
        if (outMode === "raw") {
            step = Math.max(1, raw - ctx);
        } else {
            step = raw;
        }

        let finalSegs = [];
        let droppedTail = false;
        let s = 0;
        let safety = 0;
        const minValidLen = (outMode === "raw" && ctx > 0) ? ctx + 1 : 1;
        const shotSettings = shotControls.read();
        segLenLb.textContent = shotSettings.split === "shots" ? "最长段长(总长):" : "段长(总长):";
        let detectedSettings;
        if (shotSettings.split === "shots") {
            svb.disabled = true;
            segPlan = null;
            segList.innerHTML = "";
            segOverlay.innerHTML = "";
            segStatus.textContent = "正在检测原视频镜头切换…";
            try {
                const detected = await requestShotPlan(widgetValue(node, "filename", ""), {
                    enabled: true, mode: strictH3 ? "MiniMax H3" : "普通", ...shotSettings,
                    frames: Math.round(rawLenSec * H3_FPS), seconds: rawLenSec, overlap: ctx,
                    output: outMode === "raw" ? "完整片段" : "仅新增片段",
                    start: rangeStartFrame / H3_FPS, end: rangeEndFrame / H3_FPS,
                });
                if (revision !== segmentRevision || !ov.isConnected || !segEnabled) return;
                finalSegs = detected.plan.segments;
                detectedSettings = detected.settings;
                svb.disabled = false;
            } catch (error) {
                if (revision === segmentRevision && ov.isConnected) segStatus.textContent = error.message;
                return;
            }
        } else while (s < rangeFrames && safety < 100000) {
            const e = Math.min(s + raw, rangeFrames);
            if (e - s >= minValidLen) {
                finalSegs.push({
                    start: s + rangeStartFrame,
                    end: e + rangeStartFrame,
                });
            } else if (e > s) {
                droppedTail = true;
            }
            s += step;
            safety++;
        }

        if (!finalSegs.length) {
            segStatus.textContent = "参数无效，无法分段（尾段太短）";
            segList.innerHTML = "";
            segPlan = null;
            segOverlay.innerHTML = "";
            return;
        }

        const plan = {
            fps: H3_FPS,
            raw_frames: raw,
            context_frames: outMode === "raw" ? ctx : 0,
            delivered_frames: step,
            segment_seconds: raw / H3_FPS,
            total_frames: rangeFrames,
            segment_count: finalSegs.length,
            output_mode: outMode,
            preset: segPresetSel.value,
            version: 3,
            segments: finalSegs,
            range_start_frame: rangeStartFrame,
            range_end_frame: rangeEndFrame,
            ...shotSettings,
            ...(detectedSettings ? {cuts: detectedSettings.cuts, shot_source: detectedSettings.shot_source} : {}),
        };
        segPlan = plan;

        const rawSec = raw / H3_FPS;
        const stepSec = step / H3_FPS;
        let segLenText;
        if (outMode === "raw" && ctx > 0) {
            if (showFrames) {
                segLenText = `每段总长 ${raw} 帧 · 新增 ${step} 帧（含 ${ctx} 帧重叠）`;
            } else {
                segLenText =
                    `每段总长 ${raw} 帧（${rawSec.toFixed(2)}s）· ` +
                    `新增 ${step} 帧（${stepSec.toFixed(2)}s）· 重叠 ${ctx} 帧`;
            }
        } else {
            if (showFrames) {
                segLenText = `每段 ${raw} 帧 · 无重叠`;
            } else {
                segLenText = `每段 ${raw} 帧（${rawSec.toFixed(2)}s）· 无重叠`;
            }
        }
        const rangeText = showFrames
            ? `范围内 ${rangeFrames} 帧`
            : `范围内 ${rangeFrames} 帧（${(rangeFrames / H3_FPS).toFixed(2)}s）`;
        let warnText = "";
        if (droppedTail) {
            warnText = ` · ⚠ 尾段 ≤ ${ctx} 帧重叠已丢弃`;
        }
        segStatus.textContent = shotSettings.split === "shots"
            ? `${rangeText} · 最长 ${raw} 帧（${rawSec.toFixed(2)}s，含重叠）· 按镜头切分 ${plan.segment_count} 段 · 切镜处关闭上下文`
            : `${rangeText} · ${segLenText} · 共 ${plan.segment_count} 段${warnText}`;

        segList.innerHTML = "";
        plan.segments.forEach((sg, i) => {
            const btn = document.createElement("button");
            btn.className = "yr-pgs-seg-item";
            const hue = (i * 137.508) % 360;
            btn.style.borderLeft = `3px solid hsl(${hue},70%,60%)`;
            if (showFrames) {
                btn.innerHTML = `<b>#${i}</b> ${sg.start}→${sg.end}<b>(${sg.end - sg.start})</b>`;
            } else {
                btn.innerHTML = `<b>#${i}</b> ${(sg.start / H3_FPS).toFixed(2)}→${(sg.end / H3_FPS).toFixed(2)}s<b>(${((sg.end - sg.start) / H3_FPS).toFixed(2)}s)</b>`;
            }
            btn.title = `帧 ${sg.start} ~ ${sg.end}（${sg.end - sg.start} 帧，索引 ${i}）${sg.cut_before ? " · 新镜头，不沿用上一段上下文" : ""}`;
            btn.onclick = () => {
                if (ve.readyState >= 1) ve.currentTime = sg.start / H3_FPS;
            };
            segList.appendChild(btn);
        });
        renderSegmentBars();
    }

    function applySegToggle() {
        segParamsRow.style.display = segEnabled ? "flex" : "none";
        segStatus.style.display = segEnabled ? "block" : "none";
        segList.style.display = segEnabled ? "grid" : "none";
        // ★ 按钮样式
        if (segEnabled) {
            segToggleBtn.style.background = "#0aa4d6";
            segToggleBtn.style.color = "#06131b";
            segToggleBtn.style.borderColor = "#0aa4d6";
        } else {
            segToggleBtn.style.background = "#223744";
            segToggleBtn.style.color = "#b8d2dc";
            segToggleBtn.style.borderColor = "#3a5363";
        }
        if (segEnabled) {
            recalcSegments();
        } else {
            ++segmentRevision;
            svb.disabled = false;
            segOverlay.innerHTML = "";
            segPlan = null;
        }
    }

    // ★ 按钮点击切换
    segToggleBtn.onclick = () => {
        segEnabled = !segEnabled;
        applySegToggle();
    };

    segPresetSel.onchange = () => {
        const curSec = parseFloat(segLenSel.value) || 5;
        const curCtx = parseInt(segCtxSel.value) || 0;
        rebuildSegLenOptions(curSec);
        rebuildCtxOptions(curCtx);
        if (segEnabled) recalcSegments();
    };
    segLenSel.onchange = () => { if (segEnabled) recalcSegments(); };
    segCtxSel.onchange = () => { if (segEnabled) recalcSegments(); };
    segModeSel.onchange = () => { if (segEnabled) recalcSegments(); };

    function initSegPanel() {
        if (segPanelInited || !dur) return;
        segPanelInited = true;
        const saved = node.properties?.segment_plan;
        if (saved && saved.segments && saved.segments.length) {
            shotControls.restore(saved);
            segEnabled = true;
            segPresetSel.value = saved.preset || "none";
            rebuildSegLenOptions(saved.target_seconds ?? saved.segment_seconds ?? recommendSegmentSeconds(dur * H3_FPS));
            rebuildCtxOptions(saved.context_frames ?? 22);
            segModeSel.value = saved.output_mode || "raw";
        } else {
            segEnabled = false;
            segPresetSel.value = "none";
            rebuildSegLenOptions(recommendSegmentSeconds(Math.round(dur * H3_FPS)));
            rebuildCtxOptions(22);
            segModeSel.value = "raw";
        }
        segPanel.style.display = "block";
        applySegToggle();
    }

    function initCropPanelFromSaved() {
        if (!ve.videoWidth || !ve.videoHeight) return;
        const cx = parseFloat(widgetValue(node, "crop_x", 0)) || 0;
        const cy = parseFloat(widgetValue(node, "crop_y", 0)) || 0;
        const cw = parseFloat(widgetValue(node, "crop_w", 1)) || 1;
        const ch = parseFloat(widgetValue(node, "crop_h", 1)) || 1;
        const isCropped = (cx > 0.001 || cy > 0.001 || cw < 0.999 || ch < 0.999);
        if (isCropped && !cropOn) {
            cropOn = true;
            cbtn.classList.add("on");
            cb.style.display = "block";
            ve.controls = false;
            cropSection.style.display = "block";
            cbtn.style.background = "#0aa4d6";
            cbtn.style.color = "#06131b";
            updateCb();
            updateCropPixelInputs();
        }
    }

    const ac = document.createElement("div");
    ac.style.cssText = "display:flex;justify-content:flex-end;gap:10px;margin-top:15px";
    const ccl = document.createElement("button");
    ccl.textContent = "取消";
    ccl.style.cssText = "background:#1d2b36;color:#cbd8e0;border:1px solid #3a4d5b;border-radius:4px;padding:6px 14px;cursor:pointer";
    const svb = document.createElement("button");
    svb.textContent = "保存";
    svb.style.cssText = "background:#17535a;color:#e8f6f6;border:1px solid #26717a;border-radius:4px;padding:6px 14px;cursor:pointer";
    ac.append(ccl, svb);
    dl.appendChild(ac);

    const gs = () => parseFloat(widgetValue(node, "start_time", 0)) || 0;
    const ge = () => {
        const e = parseFloat(widgetValue(node, "end_time", 0)) || 0;
        return e > 0 ? e : dur;
    };

    function updateAspectInfo() {
        if (!ve.videoWidth || !ve.videoHeight) {
            aspectInfo.style.display = "none";
            return;
        }
        const vw = ve.videoWidth;
        const vh = ve.videoHeight;
        const origText = matchAspect(vw, vh);

        const cx = parseFloat(widgetValue(node, "crop_x", 0)) || 0;
        const cy = parseFloat(widgetValue(node, "crop_y", 0)) || 0;
        const cw = parseFloat(widgetValue(node, "crop_w", 1)) || 1;
        const ch = parseFloat(widgetValue(node, "crop_h", 1)) || 1;
        const isCropped = (cx > 0.001 || cy > 0.001 || cw < 0.999 || ch < 0.999);
        const cropW = vw * cw;
        const cropH = vh * ch;
        const cropText = isCropped ? matchAspect(cropW, cropH) : null;

        const customW = parseFloat(widgetValue(node, "custom_width", 0)) || 0;
        const customH = parseFloat(widgetValue(node, "custom_height", 0)) || 0;
        const hasCustom = customW > 0 || customH > 0;

        let outW, outH;
        if (hasCustom) {
            outW = customW > 0 ? customW : cropW;
            outH = customH > 0 ? customH : cropH;
        } else {
            outW = cropW;
            outH = cropH;
        }
        const outText = matchAspect(outW, outH);

        const C = {
            orig: "#8ea3b4",
            crop: "#38bdf8",
            scale: "#f0a020",
            out:  "#4ade80",
            arrow: "#5c7785"
        };
        const arrow = `<span style="color:${C.arrow};margin:0 5px;">→</span>`;
        const dot = `<span style="color:${C.arrow};margin:0 5px;">·</span>`;

        let html = `<span style="color:${C.orig};">原 ${origText}</span>`;
        if (isCropped) {
            html += dot + `<span style="color:${C.crop};">裁 ${cropText}</span>`;
        }
        if (hasCustom) {
            html += arrow + `<span style="color:${C.scale};">缩放</span>`;
        }
        html += arrow + `<span style="color:${C.out};font-weight:bold;">参考 ${outText}</span>`;
        html += `<span style="color:${C.arrow};margin-left:6px;">(${Math.round(outW)}×${Math.round(outH)})</span>`;

        aspectInfo.innerHTML = html;
        aspectInfo.style.display = "inline-block";
    }

    function syncT() {
        const fr = parseFloat(fri.value) || 24,
            s = gs(),
            e = ge(),
            d = Math.max(0, e - s);
        setWidgetValue(node, "start_time", s);
        setWidgetValue(node, "end_time", e);
        setWidgetValue(node, "duration", d);
        setWidgetValue(node, "start_frame", Math.round(s * fr));
        setWidgetValue(node, "end_frame", Math.round(e * fr));
        setWidgetValue(node, "duration_frames", Math.round(d * fr));
        node.properties = node.properties || {};
        node.properties["duration_seconds"] = d;
    }

    function updateTS() {
        if (!dur) return;
        const s = gs(),
            e = ge();
        sh.style.left = `${s / dur * 100}%`;
        eh.style.left = `${e / dur * 100}%`;
        tf.style.left = `${s / dur * 100}%`;
        tf.style.width = `${(e - s) / dur * 100}%`;
        tr.innerHTML = "";
        for (let i = 0; i <= 5; i++) {
            const p = i / 5,
                t = dur * p;
            const d = document.createElement("div");
            d.style.cssText = `position:absolute;left:${p * 100}%;top:0;transform:translateX(-50%);font-size:9px`;
            d.textContent = mode === "frames" ? Math.round(t * parseFloat(fri.value) || 24) : fmt(t);
            tr.appendChild(d);
        }
    }

    function updateTimeInputs() {
        const fr = parseFloat(fri.value) || 24;
        if (mode === "frames") {
            startTI.lb.textContent = "开始(帧):";
            startTI.inp.step = 1;
            startTI.inp.value = Math.round(widgetValue(node, "start_frame", 0));
            endTI.lb.textContent = "结束(帧):";
            endTI.inp.step = 1;
            endTI.inp.value = Math.round(widgetValue(node, "end_frame", 0));
            durTI.lb.textContent = "时长(帧):";
            durTI.inp.step = 1;
            durTI.inp.value = Math.round(widgetValue(node, "duration_frames", 0));
        } else {
            startTI.lb.textContent = "开始(s):";
            startTI.inp.step = 0.01;
            startTI.inp.value = parseFloat(widgetValue(node, "start_time", 0));
            endTI.lb.textContent = "结束(s):";
            endTI.inp.step = 0.01;
            endTI.inp.value = parseFloat(widgetValue(node, "end_time", 0));
            durTI.lb.textContent = "时长(s):";
            durTI.inp.step = 0.01;
            durTI.inp.value = parseFloat(widgetValue(node, "duration", 0));
        }
    }

    function timeInputHandler(inp, type) {
        inp.addEventListener("input", () => {
            const v = parseFloat(inp.value) || 0;
            const fr = parseFloat(fri.value) || 24;
            if (mode === "frames") {
                if (type === "start") setWidgetValue(node, "start_frame", Math.round(v));
                else if (type === "end") setWidgetValue(node, "end_frame", Math.round(v));
                else if (type === "duration") {
                    const sf = parseInt(widgetValue(node, "start_frame", 0)) || 0;
                    setWidgetValue(node, "duration_frames", Math.round(v));
                    setWidgetValue(node, "end_frame", sf + Math.round(v));
                }
            } else {
                if (type === "start") setWidgetValue(node, "start_time", v);
                else if (type === "end") setWidgetValue(node, "end_time", v);
                else if (type === "duration") {
                    const s = parseFloat(widgetValue(node, "start_time", 0)) || 0;
                    setWidgetValue(node, "duration", v);
                    setWidgetValue(node, "end_time", s + v);
                }
            }
            syncT();
            updateTS();
            updateTimeInputs();
            updateParams();
            updateRangeOverlay();
            if (segEnabled) recalcSegments();
            if (ve && type === "start") ve.currentTime = parseFloat(widgetValue(node, "start_time", 0));
        });
    }
    timeInputHandler(startTI.inp, "start");
    timeInputHandler(endTI.inp, "end");
    timeInputHandler(durTI.inp, "duration");

    function updateAspectDimensions(changedInput) {
        if (!keepAspect) return;
        if (!ve.videoWidth || !ve.videoHeight) return;
        const isWidth = changedInput === widthInput;
        const currentVal = parseFloat(changedInput.value);
        if (isNaN(currentVal)) return;
        if (isWidth) {
            const newHeight = Math.round(currentVal / videoAspectRatio);
            heightInput.value = newHeight;
            setWidgetValue(node, "custom_height", newHeight);
        } else {
            const newWidth = Math.round(currentVal * videoAspectRatio);
            widthInput.value = newWidth;
            setWidgetValue(node, "custom_width", newWidth);
        }
    }

    widthInput.addEventListener("input", () => {
        const v = parseFloat(widthInput.value);
        if (!isNaN(v)) {
            setWidgetValue(node, "custom_width", v);
            updateAspectDimensions(widthInput);
            updateAspectInfo();
        }
    });
    heightInput.addEventListener("input", () => {
        const v = parseFloat(heightInput.value);
        if (!isNaN(v)) {
            setWidgetValue(node, "custom_height", v);
            updateAspectDimensions(heightInput);
            updateAspectInfo();
        }
    });

    function updateCropPixelInputs() {
        if (!ve.videoWidth || !ve.videoHeight) {
            cropXInput.inp.value = 0;
            cropYInput.inp.value = 0;
            cropWInput.inp.value = ve.videoWidth || 0;
            cropHInput.inp.value = ve.videoHeight || 0;
            return;
        }
        const vw = ve.videoWidth;
        const vh = ve.videoHeight;
        cropXInput.inp.value = Math.round(parseFloat(widgetValue(node, "crop_x", 0)) * vw);
        cropYInput.inp.value = Math.round(parseFloat(widgetValue(node, "crop_y", 0)) * vh);
        cropWInput.inp.value = Math.round(parseFloat(widgetValue(node, "crop_w", 1)) * vw);
        cropHInput.inp.value = Math.round(parseFloat(widgetValue(node, "crop_h", 1)) * vh);
    }

    function addPixelInputListener(inp, nodeName) {
        inp.addEventListener("input", () => {
            if (!ve.videoWidth || !ve.videoHeight) return;
            const px = parseFloat(inp.value);
            if (isNaN(px)) return;
            const vw = ve.videoWidth;
            const vh = ve.videoHeight;
            let ratio = 0;
            switch (nodeName) {
                case "crop_x": ratio = px / vw; break;
                case "crop_y": ratio = px / vh; break;
                case "crop_w": ratio = px / vw; break;
                case "crop_h": ratio = px / vh; break;
            }
            if (nodeName === "crop_w" || nodeName === "crop_h") {
                ratio = Math.max(0.01, Math.min(ratio, 1 - parseFloat(widgetValue(node, nodeName === "crop_w" ? "crop_x" : "crop_y", 0))));
            } else {
                ratio = Math.max(0, Math.min(ratio, 1 - parseFloat(widgetValue(node, nodeName === "crop_x" ? "crop_w" : "crop_h", 1))));
            }
            setWidgetValue(node, nodeName, ratio);
            updateCb();
            updateCropPixelInputs();
            updateAspectInfo();
            ratioSelect.value = "free";
        });
        inp.addEventListener("change", () => inp.dispatchEvent(new Event("input")));
    }
    addPixelInputListener(cropXInput.inp, "crop_x");
    addPixelInputListener(cropYInput.inp, "crop_y");
    addPixelInputListener(cropWInput.inp, "crop_w");
    addPixelInputListener(cropHInput.inp, "crop_h");

    function applyPresetRatio(ratioValue) {
        if (!ve.videoWidth || !ve.videoHeight) return;
        const vw = ve.videoWidth;
        const vh = ve.videoHeight;

        if (ratioValue === "free") return;

        let targetW, targetH;
        if (ratioValue === "original") {
            targetW = vw;
            targetH = vh;
        } else {
            const [rw, rh] = ratioValue.split(":").map(Number);
            const targetAspect = rw / rh;
            const videoAspect = vw / vh;

            if (videoAspect > targetAspect) {
                targetH = vh;
                targetW = Math.round(vh * targetAspect);
            } else {
                targetW = vw;
                targetH = Math.round(vw / targetAspect);
            }
        }

        const cropW = targetW / vw;
        const cropH = targetH / vh;
        const cropX = (1 - cropW) / 2;
        const cropY = (1 - cropH) / 2;

        setWidgetValue(node, "crop_x", cropX);
        setWidgetValue(node, "crop_y", cropY);
        setWidgetValue(node, "crop_w", cropW);
        setWidgetValue(node, "crop_h", cropH);

        updateCb();
        updateCropPixelInputs();
        updateAspectInfo();
    }

    ratioSelect.addEventListener("change", () => {
        applyPresetRatio(ratioSelect.value);
    });

    function updateCb() {
        const vw = ve.videoWidth,
            vh = ve.videoHeight;
        if (!vw || !vh) return;
        const r = ve.getBoundingClientRect(),
            sc = Math.min(r.width / vw, r.height / vh),
            dw = vw * sc,
            dh = vh * sc,
            ox = (r.width - dw) / 2,
            oy = (r.height - dh) / 2;
        const cx = parseFloat(widgetValue(node, "crop_x", 0)),
            cy = parseFloat(widgetValue(node, "crop_y", 0)),
            cw = parseFloat(widgetValue(node, "crop_w", 1)),
            ch = parseFloat(widgetValue(node, "crop_h", 1));
        cb.style.left = `${ox + cx * dw}px`;
        cb.style.top = `${oy + cy * dh}px`;
        cb.style.width = `${cw * dw}px`;
        cb.style.height = `${ch * dh}px`;
    }

    function updateRangeOverlay() {
        if (!dur) return;
        const vw = ve.videoWidth,
            vh = ve.videoHeight;
        if (!vw || !vh) return;
        const r = ve.getBoundingClientRect(),
            sc = Math.min(r.width / vw, r.height / vh),
            dw = vw * sc,
            dh = vh * sc,
            ox = (r.width - dw) / 2,
            oy = (r.height - dh) / 2;
        const s = gs(),
            e = ge();
        const left = ox + (s / dur) * dw;
        const width = (e - s) / dur * dw;
        rangeOverlay.style.left = `${left}px`;
        rangeOverlay.style.width = `${width}px`;
        rangeOverlay.style.bottom = `${oy}px`;
    }

    function updateParams() {
        updateCropPixelInputs();
        updateAspectInfo();
        if (ve.videoWidth && ve.videoHeight) {
            if (parseFloat(widthInput.value) === 0) {
                widthInput.value = ve.videoWidth;
                widthInput.placeholder = `原始 ${ve.videoWidth}`;
            }
            if (parseFloat(heightInput.value) === 0) {
                heightInput.value = ve.videoHeight;
                heightInput.placeholder = `原始 ${ve.videoHeight}`;
            }
        }
    }

    function onResize() {
        updateCb();
        updateRangeOverlay();
    }

    ve.onloadedmetadata = () => {
        dur = ve.duration;
        if (ve.videoWidth && ve.videoHeight) {
            videoAspectRatio = ve.videoWidth / ve.videoHeight;
            if (parseFloat(widgetValue(node, "custom_width", 0)) === 0) {
                widthInput.value = ve.videoWidth;
                widthInput.placeholder = `原始 ${ve.videoWidth}`;
            }
            if (parseFloat(widgetValue(node, "custom_height", 0)) === 0) {
                heightInput.value = ve.videoHeight;
                heightInput.placeholder = `原始 ${ve.videoHeight}`;
            }
            updateCropPixelInputs();
            updateAspectInfo();
        }
        if (ge() <= 0 || ge() > dur) setWidgetValue(node, "end_time", dur);
        syncT();
        updateTS();
        updateTimeInputs();
        updateCb();
        updateParams();
        updateRangeOverlay();
        initCropPanelFromSaved();
        initSegPanel();

        ve.ontimeupdate = () => {
            if (drg) return;
            const s = gs(),
                e = ge();
            if (e > s && ve.currentTime >= e) {
                if (loop) {
                    ve.currentTime = s;
                    ve.play().catch(() => {});
                } else {
                    ve.pause();
                    ve.currentTime = s;
                }
            } else if (ve.currentTime < s) {
                ve.currentTime = s;
            }
        };
    };

    window.addEventListener("resize", onResize);

    ts.onpointerdown = e => {
        if (!dur) return;
        const r = ts.getBoundingClientRect(),
            x = e.clientX - r.left,
            sx = gs() / dur * r.width,
            ex = ge() / dur * r.width;
        if (Math.abs(x - sx) < 10) drg = "start";
        else if (Math.abs(x - ex) < 10) drg = "end";
        else if (x > sx && x < ex) {
            drg = "center";
            off = x / r.width * dur - gs();
            selW = ge() - gs();
        } else drg = Math.abs(x - sx) < Math.abs(x - ex) ? "start" : "end";
        ts.setPointerCapture(e.pointerId);
    };
    ts.onpointermove = e => {
        if (!drg || !dur) return;
        const r = ts.getBoundingClientRect(),
            x = Math.max(0, Math.min(e.clientX - r.left, r.width)),
            v = x / r.width * dur;
        if (drg === "start") {
            if (v < ge()) setWidgetValue(node, "start_time", v);
        } else if (drg === "end") {
            if (v > gs()) setWidgetValue(node, "end_time", v);
        } else {
            let ns = v - off,
                ne = ns + selW;
            if (ns < 0) { ns = 0; ne = selW; }
            if (ne > dur) { ne = dur; ns = dur - selW; }
            setWidgetValue(node, "start_time", ns);
            setWidgetValue(node, "end_time", ne);
        }
        syncT();
        updateTS();
        updateTimeInputs();
        updateParams();
        updateRangeOverlay();
        if (ve) ve.currentTime = gs();
    };
    ts.onpointerup = () => {
        drg = null;
        if (ve) ve.currentTime = gs();
        if (segEnabled) recalcSegments();
    };

    cb.onpointerdown = e => {
        if (!cropOn) return;
        e.preventDefault();
        e.stopPropagation();
        const h = e.target.closest(".yr-pgs-ch");
        cdrg = h ? h.dataset.h : "move";
        csx = e.clientX;
        csy = e.clientY;
        ccx = parseFloat(widgetValue(node, "crop_x", 0));
        ccy = parseFloat(widgetValue(node, "crop_y", 0));
        ccw = parseFloat(widgetValue(node, "crop_w", 1));
        cch = parseFloat(widgetValue(node, "crop_h", 1));
        cb.setPointerCapture(e.pointerId);
    };
    cb.onpointermove = e => {
        if (!cropOn || !cdrg) return;
        const r = ve.getBoundingClientRect(),
            sc = Math.min(r.width / ve.videoWidth, r.height / ve.videoHeight),
            dw = ve.videoWidth * sc,
            dh = ve.videoHeight * sc;
        const dx = (e.clientX - csx) / dw,
            dy = (e.clientY - csy) / dh;
        let nx = ccx, ny = ccy, nw = ccw, nh = cch;
        if (cdrg === "move") {
            nx = Math.max(0, Math.min(ccx + dx, 1 - ccw));
            ny = Math.max(0, Math.min(ccy + dy, 1 - cch));
        } else {
            if (cdrg === "tl") {
                nw = ccw - dx; nh = cch - dy;
                nx = ccx + ccw - nw; ny = ccy + cch - nh;
            } else if (cdrg === "tr") {
                nw = ccw + dx; nh = cch - dy;
                ny = ccy + cch - nh;
            } else if (cdrg === "bl") {
                nw = ccw - dx; nh = cch + dy;
                nx = ccx + ccw - nw;
            } else if (cdrg === "br") {
                nw = ccw + dx; nh = cch + dy;
            } else if (cdrg === "tm") {
                nh = cch - dy; ny = ccy + cch - nh;
            } else if (cdrg === "bm") {
                nh = cch + dy;
            } else if (cdrg === "lm") {
                nw = ccw - dx; nx = ccx + ccw - nw;
            } else {
                nw = ccw + dx;
            }
            nw = Math.max(0.02, Math.min(nw, 1 - nx));
            nh = Math.max(0.02, Math.min(nh, 1 - ny));
            nx = Math.max(0, Math.min(nx, 1 - nw));
            ny = Math.max(0, Math.min(ny, 1 - nh));
        }
        setWidgetValue(node, "crop_x", nx);
        setWidgetValue(node, "crop_y", ny);
        setWidgetValue(node, "crop_w", nw);
        setWidgetValue(node, "crop_h", nh);
        updateCb();
        updateCropPixelInputs();
        updateAspectInfo();
        ratioSelect.value = "free";
    };
    cb.onpointerup = () => { cdrg = null; };

    ccl.onclick = () => {
        ov.remove();
        currentVideoEditor = null;
        window.removeEventListener("resize", onResize);
    };
    svb.onclick = () => {
        if (segEnabled && !segPlan) return;
        if (segEnabled && segPlan) {
            const saved = {
                ...segPlan,
                target_seconds: parseFloat(segLenSel.value) || 5,
                preset: segPresetSel.value,
            };
            node.properties = node.properties || {};
            node.properties.segment_plan = saved;
            setWidgetValue(node, "segment_plan_json", JSON.stringify(saved));
        } else {
            node.properties = node.properties || {};
            delete node.properties.segment_plan;
            setWidgetValue(node, "segment_plan_json", "");
        }

        const origCustomWidth = parseFloat(widgetValue(node, "custom_width", 0));
        const origCustomHeight = parseFloat(widgetValue(node, "custom_height", 0));
        let finalWidth = parseFloat(widthInput.value);
        let finalHeight = parseFloat(heightInput.value);
        if (origCustomWidth === 0 && finalWidth === ve.videoWidth) finalWidth = 0;
        if (origCustomHeight === 0 && finalHeight === ve.videoHeight) finalHeight = 0;

        setWidgetValue(node, "custom_width", finalWidth);
        setWidgetValue(node, "custom_height", finalHeight);
        setWidgetValue(node, "resize_method", rs.value);
        setWidgetValue(node, "frame_rate", parseFloat(fri.value) || 24);
        setWidgetValue(node, "display_mode", mode);
        syncT();

        ov.remove();
        currentVideoEditor = null;
        window.removeEventListener("resize", onResize);

        if (node._pgsVideoRender) {
            node._pgsVideoRender();
            setTimeout(() => node._pgsVideoRender(), 300);
        }
    };

    updateTS();
    updateTimeInputs();
    updateCb();
    updateParams();
    updateRangeOverlay();
}
