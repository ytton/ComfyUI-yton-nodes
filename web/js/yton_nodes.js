import { app } from "../../../scripts/app.js";
import { setupMediaLoaderNode } from "./media_loader_panel.js";
import { mountNodePanel, followNodeColours } from "./node_panel.js";

// Load external CSS
const link = document.createElement("link");
link.rel = "stylesheet";
link.type = "text/css";
link.href = new URL("../css/yton_nodes.css", import.meta.url).href;
document.head.appendChild(link);

const RATIO_DIMS = {
  "16:9": { w: 24, h: 14 },
  "9:16": { w: 14, h: 24 },
  "1:1":  { w: 18, h: 18 },
  "4:3":  { w: 22, h: 16 },
  "3:4":  { w: 16, h: 22 },
  "3:2":  { w: 22, h: 15 },
  "2:3":  { w: 15, h: 22 },
  "21:9": { w: 26, h: 11 },
};

const MP_MAP = {
  "320p": "0.3",
  "480p": "0.4",
  "540p": "0.5",
  "640p": "0.7",
  "720p": "0.9",
  "768p": "1.0",
  "944p": "1.5",
  "1024p": "1.8",
  "1080p": "2.0",
};

const LIST_PARSERS = new Set(["YtonImageListParser", "YtonVideoListParser", "YtonAudioListParser"]);

app.registerExtension({
  name: "yton.nodes",
  async nodeCreated(node) {
    if (["YtonResolutionSelector", "YtonResolutionSelectorSimple"].includes(node.comfyClass)) {
      setupResolutionNode(node);
    } else if (node.comfyClass === "YtonEasyMediaLoader") {
      setupMediaLoaderNode(node);
    } else if (LIST_PARSERS.has(node.comfyClass)) {
      const showListInput = () => {
        for (const input of node.inputs || []) input.shape = LiteGraph.GRID_SHAPE;
        node.setDirtyCanvas(true, true);
      };
      const configure = node.onConfigure;
      node.onConfigure = function () {
        const result = configure?.apply(this, arguments);
        showListInput();
        return result;
      };
      showListInput();
    }
  }
});

// ==========================================
// 1. Resolution Controller Setup
// ==========================================
function setupResolutionNode(node) {
  const modeWidget = node.widgets?.find(w => w.name === "mode");
  const ratioWidget = node.widgets?.find(w => w.name === "aspect_ratio");
  const resWidget = node.widgets?.find(w => w.name === "resolution");
  const visibilityWidget = node.widgets?.find(w => w.name === "option_visibility");
  node.convertWidgetToInput(ratioWidget);
  hideNodeWidgets(node);

  const container = document.createElement("div");
  container.className = "yton-panel yton-resolution-panel";

  // Header & Mode segmented switch
  const header = document.createElement("div");
  header.className = "yton-header-row";

  const title = document.createElement("div");
  title.className = "yton-title";
  title.innerText = "画幅与分辨率";

  const segmented = document.createElement("div");
  segmented.className = "yton-segmented";

  const h3Btn = document.createElement("button");
  h3Btn.className = "yton-segment-btn";
  h3Btn.type = "button";
  h3Btn.innerText = "MiniMax H3";

  const normalBtn = document.createElement("button");
  normalBtn.className = "yton-segment-btn";
  normalBtn.type = "button";
  normalBtn.innerText = "普通 / 图片";

  segmented.appendChild(h3Btn);
  segmented.appendChild(normalBtn);
  header.appendChild(title);
  header.appendChild(segmented);
  container.appendChild(header);

  // Resolution Section
  const resSection = document.createElement("div");
  resSection.className = "yton-section";
  const resLabel = document.createElement("div");
  resLabel.className = "yton-label";
  resLabel.innerText = "输出分辨率";
  resSection.appendChild(resLabel);

  const resGrid = document.createElement("div");
  resGrid.className = "yton-grid-pills";
  resSection.appendChild(resGrid);
  container.appendChild(resSection);

  // Ratio Section
  const ratioSection = document.createElement("div");
  ratioSection.className = "yton-section";
  const ratioLabel = document.createElement("div");
  ratioLabel.className = "yton-label";
  ratioLabel.innerText = "画面比例";
  ratioSection.appendChild(ratioLabel);

  const ratioGrid = document.createElement("div");
  ratioGrid.className = "yton-grid-ratios";
  ratioSection.appendChild(ratioGrid);
  container.appendChild(ratioSection);

  const footer = document.createElement("div");
  footer.className = "yton-resolution-footer";
  const settings = document.createElement("button");
  settings.type = "button";
  settings.className = "yton-resolution-settings";
  settings.title = "设置可见的分辨率与比例";
  settings.setAttribute("aria-label", settings.title);
  settings.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 3-.6 2.4-2 .9L4.2 5.6 2 9.4l1.8 1.7v2L2 14.8l2.2 3.8 2.2-.7 2 .9L9 21h4l.6-2.2 2-.9 2.2.7 2.2-3.8-1.8-1.7v-2L20 9.4l-2.2-3.8-2.2.7-2-.9L13 3Z"/><circle cx="11" cy="12" r="3"/></svg>';
  const popover = document.createElement("div");
  popover.className = "yton-resolution-popover";
  popover.popover = "auto";
  const popoverTitle = document.createElement("strong");
  popoverTitle.textContent = "显示选项";
  const settingsList = document.createElement("div");
  settingsList.className = "yton-resolution-settings-list";
  popover.append(popoverTitle, settingsList);
  footer.append(settings, popover);
  container.append(footer);
  settings.onclick = () => {
    if (popover.matches(":popover-open")) { popover.hidePopover(); return; }
    renderSettings();
    popover.showPopover();
    const rect = settings.getBoundingClientRect();
    const bounds = container.closest("[data-node-id]")?.getBoundingClientRect() || container.getBoundingClientRect();
    const scale = container.getBoundingClientRect().width / container.offsetWidth;
    const right = bounds.right + 18 * scale;
    const left = bounds.left - 18 * scale - popover.offsetWidth;
    popover.style.left = `${right + popover.offsetWidth <= innerWidth - 8 || left < 8 ? right : left}px`;
    popover.style.top = `${Math.max(8, Math.min(rect.top - popover.offsetHeight - 6, innerHeight - popover.offsetHeight - 8))}px`;
  };
  popover.addEventListener("toggle", () => settings.setAttribute("aria-expanded", String(popover.matches(":popover-open"))));
  settings.setAttribute("aria-expanded", "false");

  function visibility() {
    return JSON.parse(visibilityWidget.value || "{}");
  }
  function hiddenOptions(kind) {
    return visibility()[modeWidget.value]?.[kind] ?? (kind === "ratios" ? ["auto"] : []);
  }
  function isLinked(name) {
    return node.inputs?.some(input => input.name === name && input.link != null);
  }
  const eyeIcon = visible => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>${visible ? "" : '<path d="m3 3 18 18"/>'}</svg>`;
  function renderSettings() {
    settingsList.replaceChildren();
    for (const [kind, label, options] of [["resolutions", "分辨率", resolutionOptions()], ["ratios", "画面比例", ratioOptions()]]) {
      const heading = document.createElement("div");
      heading.className = "yton-label";
      heading.textContent = label;
      settingsList.append(heading);
      const hidden = hiddenOptions(kind);
      for (const value of options) {
        const visible = !hidden.includes(value);
        const row = document.createElement("div");
        row.className = "yton-resolution-option-row";
        const text = document.createElement("span");
        text.textContent = value === "auto" ? "自动" : value;
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.innerHTML = eyeIcon(visible);
        toggle.title = `${visible ? "隐藏" : "显示"} ${value === "auto" ? "自动" : value}`;
        toggle.setAttribute("aria-label", toggle.title);
        toggle.setAttribute("aria-pressed", String(visible));
        toggle.disabled = visible && options.filter(option => !hidden.includes(option)).length === 1;
        toggle.onclick = () => {
          const state = visibility();
          state[modeWidget.value] ??= {};
          state[modeWidget.value][kind] = visible ? [...hidden, value] : hidden.filter(option => option !== value);
          changeValue(visibilityWidget, JSON.stringify(state));
        };
        row.append(text, toggle);
        settingsList.append(row);
      }
    }
  }

  function resolutionOptions() {
    return modeWidget.value.includes("H3")
      ? ["320p", "480p", "540p", "640p", "720p", "768p", "944p", "1024p", "1080p"]
      : ["480p", "540p", "640p", "720p", "1080p", "2K", "2.5K", "4K", "6K"];
  }

  function renderResolutions() {
    resGrid.innerHTML = "";
    const isH3 = modeWidget?.value?.includes("H3");
    const options = resolutionOptions().filter(value => !hiddenOptions("resolutions").includes(value));
    if (!options.includes(resWidget.value)) resWidget.value = options[0];

    options.forEach(opt => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "yton-pill-btn" + (resWidget.value === opt ? " active" : "");
      btn.setAttribute("aria-pressed", String(resWidget.value === opt));
      
      const text = document.createElement("span");
      text.innerText = opt;
      btn.appendChild(text);

      if (isH3 && MP_MAP[opt]) {
        const sub = document.createElement("span");
        sub.className = "yton-subtext";
        sub.innerText = `(${MP_MAP[opt]})`;
        btn.appendChild(sub);
      }

      btn.onclick = () => {
        changeValue(resWidget, opt);
      };
      resGrid.appendChild(btn);
    });
  }

  function ratioOptions() {
    const ratios = ["auto", "16:9", "9:16", "1:1", "4:3", "3:4", "2:3", "3:2", "21:9"];
    return ratios;
  }
  function renderRatios() {
    ratioGrid.innerHTML = "";
    const ratios = ratioOptions().filter(value => !hiddenOptions("ratios").includes(value));
    if (!ratios.includes(ratioWidget.value)) ratioWidget.value = ratios[0];
    ratioGrid.hidden = isLinked("aspect_ratio");
    ratioLabel.textContent = ratioGrid.hidden ? "画面比例 · 跟随输入" : "画面比例";
    ratios.forEach(r => {
      const card = document.createElement("button");
      card.type = "button";
      card.setAttribute("aria-label", `画面比例 ${r === "auto" ? "自动" : r}`);
      if (r === "auto") card.title = "按输入图片匹配最接近的预设比例；未接图片时使用 16:9";
      card.setAttribute("aria-pressed", String(ratioWidget.value === r));
      card.className = "yton-ratio-card" + (ratioWidget.value === r ? " active" : "");

      const icon = document.createElement("div");
      icon.className = "yton-ratio-icon";
      const dim = RATIO_DIMS[r] || { w: 20, h: 20 };
      icon.style.width = `${dim.w}px`;
      icon.style.height = `${dim.h}px`;
      if (r === "auto") { icon.classList.add("yton-ratio-auto"); icon.textContent = "A"; }

      const txt = document.createElement("div");
      txt.className = "yton-ratio-text";
      txt.innerText = r === "auto" ? "自动" : r;

      card.appendChild(icon);
      card.appendChild(txt);

      card.onclick = () => {
        changeValue(ratioWidget, r);
      };
      ratioGrid.appendChild(card);
    });
  }

  function render() {
    const isH3 = modeWidget.value.includes("H3");
    h3Btn.classList.toggle("active", isH3);
    normalBtn.classList.toggle("active", !isH3);
    h3Btn.setAttribute("aria-pressed", String(isH3));
    normalBtn.setAttribute("aria-pressed", String(!isH3));
    renderResolutions();
    renderRatios();
    if (popover.matches(":popover-open")) renderSettings();
    node.setDirtyCanvas(true, true);
  }

  function changeValue(widget, value) {
    if (widget.value === value) return;
    node.graph?.beforeChange();
    widget.value = value;
    widget.callback?.(value);
    node.graph?.afterChange();
  }

  h3Btn.onclick = () => changeValue(modeWidget, "MiniMax H3 (Video)");
  normalBtn.onclick = () => changeValue(modeWidget, "Normal (Standard Image/Video)");

  for (const widget of [modeWidget, ratioWidget, resWidget, visibilityWidget]) {
    const callback = widget.callback;
    widget.callback = function () {
      const result = callback?.apply(this, arguments);
      render();
      return result;
    };
  }
  const onConfigure = node.onConfigure;
  node.onConfigure = function () {
    const result = onConfigure?.apply(this, arguments);
    render();
    return result;
  };
  const onConnectionsChange = node.onConnectionsChange;
  node.onConnectionsChange = function () {
    const result = onConnectionsChange?.apply(this, arguments);
    queueMicrotask(render);
    return result;
  };

  render();
  followNodeColours(node, container);
  mountNodePanel(node, "resolution_ui", container, 360, 310, { fitHeight: true });
}

// Suppress native widgets across LiteGraph v1 AND ComfyUI Frontend 2.0 (Vue-based)
function hideNodeWidgets(node) {
  if (!node.widgets) return;
  for (const w of node.widgets) {
    if (w.name && w.name.includes("custom_ui")) continue;
    w.type = "hidden";
    w.computeSize = () => [0, 0];
    w.computeLayoutSize = () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
    w.draw = () => {}; // suppress LiteGraph canvas drawing
    w.hidden = true;
    if (w.options) {
      w.options.hidden = true;
    }
    // ComfyUI 2.0 DOM element suppression
    if (w.element) {
      w.element.style.display = "none";
      w.element.style.height = "0px";
      w.element.style.minHeight = "0px";
      w.element.style.margin = "0px";
      w.element.style.padding = "0px";
    }
  }
}
