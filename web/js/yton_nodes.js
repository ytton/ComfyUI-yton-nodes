import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

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
  "360p": "0.2",
  "480p": "0.4",
  "540p": "0.5",
  "640p": "0.7",
  "720p": "0.9",
  "1080p": "2.0",
  "1K": "0.8",
  "2K": "1.5",
  "4K": "3.0"
};

app.registerExtension({
  name: "yton.nodes",
  async nodeCreated(node) {
    if (node.comfyClass === "YtonResolutionSelector") {
      setupResolutionNode(node);
    } else if (node.comfyClass === "YtonEasyMediaLoader") {
      setupMediaLoaderNode(node);
    }
  }
});

// ==========================================
// 1. Resolution Controller Setup
// ==========================================
function setupResolutionNode(node) {
  // Find underlying widget references
  const modeWidget = node.widgets.find(w => w.name === "mode");
  const ratioWidget = node.widgets.find(w => w.name === "aspect_ratio");
  const resWidget = node.widgets.find(w => w.name === "resolution");

  // Hide default raw dropdowns
  if (modeWidget) modeWidget.type = "hidden";
  if (ratioWidget) ratioWidget.type = "hidden";
  if (resWidget) resWidget.type = "hidden";

  const container = document.createElement("div");
  container.className = "yton-panel";

  // Header & Mode segmented switch
  const header = document.createElement("div");
  header.className = "yton-header-row";

  const title = document.createElement("div");
  title.className = "yton-title";
  title.innerText = "画幅与分辨率";

  const segmented = document.createElement("div");
  segmented.className = "yton-segmented";

  const h3Btn = document.createElement("button");
  h3Btn.className = "yton-segment-btn" + (modeWidget.value.includes("H3") ? " active" : "");
  h3Btn.innerText = "MiniMax H3";

  const normalBtn = document.createElement("button");
  normalBtn.className = "yton-segment-btn" + (!modeWidget.value.includes("H3") ? " active" : "");
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

  function renderResolutions() {
    resGrid.innerHTML = "";
    const isH3 = modeWidget.value.includes("H3");
    const options = isH3 
      ? ["360p", "480p", "540p", "640p", "720p", "1080p"]
      : ["360p", "540p", "720p", "1080p", "1K", "2K", "4K"];

    options.forEach(opt => {
      const btn = document.createElement("button");
      btn.className = "yton-pill-btn" + (resWidget.value === opt ? " active" : "");
      
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
        resWidget.value = opt;
        renderResolutions();
        app.graph.setDirtyCanvas(true, true);
      };
      resGrid.appendChild(btn);
    });
  }

  function renderRatios() {
    ratioGrid.innerHTML = "";
    const ratios = ["16:9", "9:16", "1:1", "4:3", "3:4", "2:3", "3:2", "21:9"];
    ratios.forEach(r => {
      const card = document.createElement("div");
      card.className = "yton-ratio-card" + (ratioWidget.value === r ? " active" : "");

      const icon = document.createElement("div");
      icon.className = "yton-ratio-icon";
      const dim = RATIO_DIMS[r] || { w: 20, h: 20 };
      icon.style.width = `${dim.w}px`;
      icon.style.height = `${dim.h}px`;

      const txt = document.createElement("div");
      txt.className = "yton-ratio-text";
      txt.innerText = r;

      card.appendChild(icon);
      card.appendChild(txt);

      card.onclick = () => {
        ratioWidget.value = r;
        renderRatios();
        app.graph.setDirtyCanvas(true, true);
      };
      ratioGrid.appendChild(card);
    });
  }

  h3Btn.onclick = () => {
    modeWidget.value = "MiniMax H3 (Video)";
    h3Btn.classList.add("active");
    normalBtn.classList.remove("active");
    renderResolutions();
    app.graph.setDirtyCanvas(true, true);
  };

  normalBtn.onclick = () => {
    modeWidget.value = "Normal (Standard Image/Video)";
    normalBtn.classList.add("active");
    h3Btn.classList.remove("active");
    renderResolutions();
    app.graph.setDirtyCanvas(true, true);
  };

  renderResolutions();
  renderRatios();

  node.addDOMWidget("resolution_ui", "custom_ui", container);
  node.setSize([340, 360]);
}

// ==========================================
// 2. Media Loader Setup
// ==========================================
function setupMediaLoaderNode(node) {
  const manifestWidget = node.widgets.find(w => w.name === "media_manifest");
  const imgLimitWidget = node.widgets.find(w => w.name === "image_limit");
  const audioLimitWidget = node.widgets.find(w => w.name === "audio_limit");
  const videoLimitWidget = node.widgets.find(w => w.name === "video_limit");

  if (manifestWidget) manifestWidget.type = "hidden";
  if (imgLimitWidget) imgLimitWidget.type = "hidden";
  if (audioLimitWidget) audioLimitWidget.type = "hidden";
  if (videoLimitWidget) videoLimitWidget.type = "hidden";

  let mediaList = [];
  try {
    mediaList = JSON.parse(manifestWidget.value || "[]");
  } catch (e) {
    mediaList = [];
  }

  const container = document.createElement("div");
  container.className = "yton-panel";

  // Header row
  const header = document.createElement("div");
  header.className = "yton-header-row";

  const title = document.createElement("div");
  title.className = "yton-title";
  title.innerText = "媒体资源";

  const uploadBtn = document.createElement("button");
  uploadBtn.className = "yton-upload-btn";
  uploadBtn.innerText = "上传媒体";

  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.multiple = true;
  fileInput.accept = "image/*,video/*,audio/*";
  fileInput.style.display = "none";

  uploadBtn.onclick = () => fileInput.click();

  header.appendChild(title);
  header.appendChild(uploadBtn);
  header.appendChild(fileInput);
  container.appendChild(header);

  // Sections
  const imageSection = createMediaCategory("图片", "image", imgLimitWidget);
  const audioSection = createMediaCategory("音频", "audio", audioLimitWidget);
  const videoSection = createMediaCategory("视频", "video", videoLimitWidget);

  container.appendChild(imageSection.el);
  container.appendChild(audioSection.el);
  container.appendChild(videoSection.el);

  function createMediaCategory(label, type, limitWidget) {
    const el = document.createElement("div");
    el.className = "yton-section";

    const row = document.createElement("div");
    row.className = "yton-media-row-header";

    const titleEl = document.createElement("span");
    titleEl.className = "yton-label";
    titleEl.innerText = `${label}`;

    const limitWrapper = document.createElement("div");
    limitWrapper.style.display = "flex";
    limitWrapper.style.alignItems = "center";
    limitWrapper.style.gap = "4px";

    const limitLabel = document.createElement("span");
    limitLabel.className = "yton-subtext";
    limitLabel.innerText = "上限:";

    const input = document.createElement("input");
    input.type = "number";
    input.className = "yton-limit-input";
    input.value = limitWidget.value;
    input.min = "1";
    input.max = "16";

    input.onchange = () => {
      limitWidget.value = parseInt(input.value) || 1;
      updateUI();
      app.graph.setDirtyCanvas(true, true);
    };

    limitWrapper.appendChild(limitLabel);
    limitWrapper.appendChild(input);

    row.appendChild(titleEl);
    row.appendChild(limitWrapper);
    el.appendChild(row);

    const grid = document.createElement("div");
    grid.className = "yton-media-grid";
    el.appendChild(grid);

    return { el, grid, type, limitWidget };
  }

  function syncManifest() {
    manifestWidget.value = JSON.stringify(mediaList);
    app.graph.setDirtyCanvas(true, true);
  }

  function updateUI() {
    [imageSection, audioSection, videoSection].forEach(sec => {
      sec.grid.innerHTML = "";
      const filtered = mediaList.filter(m => m.type === sec.type);
      if (filtered.length === 0) {
        const empty = document.createElement("div");
        empty.className = "yton-media-empty";
        empty.innerText = "暂无媒体";
        sec.grid.appendChild(empty);
      } else {
        filtered.forEach((item, idx) => {
          const card = document.createElement("div");
          card.className = "yton-media-item";

          if (item.type === "image") {
            const img = document.createElement("img");
            img.className = "yton-media-thumb";
            img.src = api.apiURL(`/view?filename=${encodeURIComponent(item.filename)}&type=input&subfolder=${encodeURIComponent(item.subfolder || "")}`);
            card.appendChild(img);
          } else if (item.type === "video") {
            const v = document.createElement("video");
            v.className = "yton-media-thumb";
            v.src = api.apiURL(`/view?filename=${encodeURIComponent(item.filename)}&type=input&subfolder=${encodeURIComponent(item.subfolder || "")}`);
            card.appendChild(v);
            if (item.duration) {
              const durBadge = document.createElement("div");
              durBadge.className = "yton-badge-duration";
              durBadge.innerText = item.duration;
              card.appendChild(durBadge);
            }
          } else if (item.type === "audio") {
            card.style.display = "flex";
            card.style.alignItems = "center";
            card.style.justifyContent = "center";
            card.innerHTML = `<span style="font-size:20px;">🎵</span>`;
          }

          const badge = document.createElement("div");
          badge.className = "yton-badge-index";
          badge.innerText = `${idx + 1}`;
          card.appendChild(badge);

          const rm = document.createElement("div");
          rm.className = "yton-remove-btn";
          rm.innerText = "×";
          rm.onclick = (e) => {
            e.stopPropagation();
            mediaList = mediaList.filter(m => m !== item);
            syncManifest();
            updateUI();
          };
          card.appendChild(rm);

          sec.grid.appendChild(card);
        });
      }
    });
  }

  // Upload handling
  fileInput.onchange = async () => {
    const files = Array.from(fileInput.files);
    for (const file of files) {
      const type = file.type.startsWith("image/") ? "image"
                 : file.type.startsWith("video/") ? "video"
                 : file.type.startsWith("audio/") ? "audio" : null;
      if (!type) continue;

      const currentCount = mediaList.filter(m => m.type === type).length;
      const limit = (type === "image" ? imgLimitWidget.value
                  : type === "audio" ? audioLimitWidget.value
                  : videoLimitWidget.value);

      if (currentCount >= limit) {
        alert(`${type} 数量已达上限 (${limit})，无法继续添加！`);
        continue;
      }

      const formData = new FormData();
      formData.append("image", file);
      formData.append("overwrite", "true");

      try {
        const resp = await api.fetchApi("/upload/image", { method: "POST", body: formData });
        const res = await resp.json();
        
        let duration = "";
        if (type === "video") {
          duration = "0:05"; // default fallback badge
        }

        mediaList.push({
          type,
          filename: res.name,
          subfolder: res.subfolder || "",
          duration
        });
      } catch (err) {
        console.error("Upload failed", err);
      }
    }
    fileInput.value = "";
    syncManifest();
    updateUI();
  };

  updateUI();
  node.addDOMWidget("media_loader_ui", "custom_ui", container);
  node.setSize([360, 420]);
}
