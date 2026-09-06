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
  "1K": "1.0",
  "2K": "1.5",
  "4K": "2.5",
  "6K": "4.0"
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
  // Hide all underlying default widgets from canvas render
  hideNodeWidgets(node);

  const modeWidget = node.widgets?.find(w => w.name === "mode");
  const ratioWidget = node.widgets?.find(w => w.name === "aspect_ratio");
  const resWidget = node.widgets?.find(w => w.name === "resolution");

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
    const isH3 = modeWidget?.value?.includes("H3");
    // Both modes have 6 options for symmetry (2 rows x 3 columns)
    const options = isH3 
      ? ["360p", "480p", "540p", "640p", "720p", "1080p"]
      : ["540p", "720p", "1K", "2K", "4K", "6K"];

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
  
  const RES_W = 340;
  const RES_H = 360;
  node.setSize([RES_W, RES_H]);
  node.onResize = function(size) {
    size[0] = Math.max(size[0], RES_W);
    size[1] = Math.max(size[1], RES_H);
  };
}

function hideNodeWidgets(node) {
  if (!node.widgets) return;
  for (const w of node.widgets) {
    w.type = "hidden";
    w.computeSize = () => [0, -4];
    w.draw = () => {}; // suppress LiteGraph canvas drawing
  }
}

// ==========================================
// 2. Media Loader Setup
// ==========================================
function setupMediaLoaderNode(node) {
  // Hide all underlying widgets from canvas render
  hideNodeWidgets(node);

  const imgLimitWidget = node.widgets?.find(w => w.name === "image_limit");
  const audioLimitWidget = node.widgets?.find(w => w.name === "audio_limit");
  const videoLimitWidget = node.widgets?.find(w => w.name === "video_limit");

  // Read current assets from explicit widgets (image_1~9, audio_1~3, video_1~3)
  function readMediaFromWidgets() {
    const list = [];
    for (let i = 1; i <= 9; i++) {
      const w = node.widgets?.find(x => x.name === `image_${i}`);
      if (w && w.value && w.value.trim()) {
        list.push({ type: "image", filename: w.value.trim() });
      }
    }
    for (let i = 1; i <= 3; i++) {
      const w = node.widgets?.find(x => x.name === `audio_${i}`);
      if (w && w.value && w.value.trim()) {
        list.push({ type: "audio", filename: w.value.trim() });
      }
    }
    for (let i = 1; i <= 3; i++) {
      const w = node.widgets?.find(x => x.name === `video_${i}`);
      if (w && w.value && w.value.trim()) {
        list.push({ type: "video", filename: w.value.trim() });
      }
    }
    return list;
  }

  let mediaList = readMediaFromWidgets();

  const container = document.createElement("div");
  container.className = "yton-panel";

  // Whole-node drop handler: auto-route files by MIME/extension anywhere on the node
  container.ondragover = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  container.ondrop = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    [imageSection, audioSection, videoSection].forEach(s => s?.grid?.classList?.remove("drag-over"));
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      await handleFilesUpload(Array.from(e.dataTransfer.files));
    }
  };

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
    input.value = limitWidget ? limitWidget.value : (type === "image" ? 9 : 3);
    input.min = "1";
    input.max = (type === "image" ? "9" : "3");

    input.onchange = () => {
      if (limitWidget) limitWidget.value = parseInt(input.value) || 1;
      updateUI();
      app.graph.setDirtyCanvas(true, true);
    };

    limitWrapper.appendChild(limitLabel);
    limitWrapper.appendChild(input);

    row.appendChild(titleEl);
    row.appendChild(limitWrapper);
    el.appendChild(row);

    const grid = document.createElement("div");
    grid.className = "yton-media-grid " + (type === "image" ? "image-grid" : "single-row-grid");

    // Setup drag-and-drop visual cue (actual drop handled by container or grid by MIME routing)
    grid.ondragover = (e) => {
      e.preventDefault();
      e.stopPropagation();
      grid.classList.add("drag-over");
    };

    grid.ondragleave = (e) => {
      e.preventDefault();
      e.stopPropagation();
      grid.classList.remove("drag-over");
    };

    grid.ondrop = async (e) => {
      e.preventDefault();
      e.stopPropagation();
      grid.classList.remove("drag-over");
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        // Automatically route all dropped files by their MIME type
        await handleFilesUpload(Array.from(e.dataTransfer.files));
      }
    };

    el.appendChild(grid);

    return { el, grid, type, limitWidget, input };
  }

  // Write mediaList back to discrete standard widgets: image_1~9, audio_1~3, video_1~3
  function syncManifest() {
    const images = mediaList.filter(m => m.type === "image");
    const audios = mediaList.filter(m => m.type === "audio");
    const videos = mediaList.filter(m => m.type === "video");

    for (let i = 1; i <= 9; i++) {
      const w = node.widgets?.find(x => x.name === `image_${i}`);
      if (w) w.value = (i <= images.length) ? images[i - 1].filename : "";
    }
    for (let i = 1; i <= 3; i++) {
      const w = node.widgets?.find(x => x.name === `audio_${i}`);
      if (w) w.value = (i <= audios.length) ? audios[i - 1].filename : "";
    }
    for (let i = 1; i <= 3; i++) {
      const w = node.widgets?.find(x => x.name === `video_${i}`);
      if (w) w.value = (i <= videos.length) ? videos[i - 1].filename : "";
    }

    updateDynamicOutputs();
    app.graph.setDirtyCanvas(true, true);
  }

  // Hook for workflow JSON load / configure
  const origOnConfigure = node.onConfigure;
  node.onConfigure = function() {
    if (origOnConfigure) origOnConfigure.apply(this, arguments);
    mediaList = readMediaFromWidgets();
    if (imgLimitWidget && imageSection.input) imageSection.input.value = imgLimitWidget.value;
    if (audioLimitWidget && audioSection.input) audioSection.input.value = audioLimitWidget.value;
    if (videoLimitWidget && videoSection.input) videoSection.input.value = videoLimitWidget.value;
    updateDynamicOutputs();
    updateUI();
  };

  // Dynamic Output Slots based on actual media count
  function updateDynamicOutputs() {
    const images = mediaList.filter(m => m.type === "image");
    const audios = mediaList.filter(m => m.type === "audio");
    const videos = mediaList.filter(m => m.type === "video");

    // Desired output schema:
    // 0: media_bundle (always present)
    // image_1 ... image_N
    // audio_1 ... audio_N
    // video_1_path ... video_N_path
    const targetOutputs = [
      { name: "media_bundle", type: "MEDIA_BUNDLE" }
    ];

    images.forEach((_, idx) => {
      targetOutputs.push({ name: `image_${idx + 1}`, type: "IMAGE" });
    });
    audios.forEach((_, idx) => {
      targetOutputs.push({ name: `audio_${idx + 1}`, type: "AUDIO" });
    });
    videos.forEach((_, idx) => {
      targetOutputs.push({ name: `video_${idx + 1}_path`, type: "STRING" });
    });

    // Save existing output links
    const existingLinks = [];
    if (node.outputs) {
      node.outputs.forEach(out => {
        if (out.links && out.links.length > 0) {
          existingLinks.push({ name: out.name, type: out.type, links: [...out.links] });
        }
      });
    }

    // Reconstruct node.outputs
    const newOutputs = [];
    targetOutputs.forEach(target => {
      const matchExisting = existingLinks.find(l => l.name === target.name);
      newOutputs.push({
        name: target.name,
        type: target.type,
        links: matchExisting ? matchExisting.links : null
      });
    });

    node.outputs = newOutputs;
  }

  let draggedItem = null;

  function updateUI() {
    [imageSection, audioSection, videoSection].forEach(sec => {
      sec.grid.innerHTML = "";
      const filtered = mediaList.filter(m => m.type === sec.type);
      if (filtered.length === 0) {
        const empty = document.createElement("div");
        empty.className = "yton-media-empty";
        empty.innerText = "拖拽或上传素材";
        sec.grid.appendChild(empty);
      } else {
        filtered.forEach((item, idx) => {
          const card = document.createElement("div");
          card.className = "yton-media-item";
          card.draggable = true;

          // Drag-to-reorder events
          card.ondragstart = (e) => {
            draggedItem = item;
            card.classList.add("dragging");
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", `${item.type}:${idx}`);
          };

          card.ondragend = () => {
            card.classList.remove("dragging");
            draggedItem = null;
          };

          card.ondragover = (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
          };

          card.ondrop = (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (!draggedItem || draggedItem.type !== item.type || draggedItem === item) return;

            // Reorder specifically within the same media type
            const sameTypeItems = mediaList.filter(m => m.type === item.type);
            const fromIdx = sameTypeItems.indexOf(draggedItem);
            const toIdx = sameTypeItems.indexOf(item);
            if (fromIdx > -1 && toIdx > -1 && fromIdx !== toIdx) {
              sameTypeItems.splice(fromIdx, 1);
              sameTypeItems.splice(toIdx, 0, draggedItem);
              
              // Rebuild mediaList keeping other types intact
              const otherItems = mediaList.filter(m => m.type !== item.type);
              mediaList = [...otherItems, ...sameTypeItems];
              draggedItem = null;
              syncManifest();
              updateUI();
            }
          };

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

  // Upload handler: routes files by extension / MIME to appropriate slot
  async function handleFilesUpload(files) {
    for (const file of files) {
      const ext = file.name.split(".").pop().toLowerCase();
      let type = null;

      // 1. Detect image
      if (file.type.startsWith("image/") || ["png", "jpg", "jpeg", "webp", "gif", "bmp"].includes(ext)) {
        type = "image";
      }
      // 2. Detect video
      else if (file.type.startsWith("video/") || ["mp4", "webm", "mov", "avi", "mkv"].includes(ext)) {
        type = "video";
      }
      // 3. Detect audio
      else if (file.type.startsWith("audio/") || ["mp3", "wav", "ogg", "flac", "m4a", "aac"].includes(ext)) {
        type = "audio";
      }
      if (!type) continue;

      const currentCount = mediaList.filter(m => m.type === type).length;
      const limit = (type === "image" ? (imgLimitWidget?.value || 9)
                  : type === "audio" ? (audioLimitWidget?.value || 3)
                  : (videoLimitWidget?.value || 3));

      if (currentCount >= limit) {
        alert(`${type === "image" ? "图片" : type === "video" ? "视频" : "音频"} 数量已达上限 (${limit})，无法继续添加！`);
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
          duration = "0:05";
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
    syncManifest();
    updateUI();
  }

  // Upload handling via button
  fileInput.onchange = async () => {
    await handleFilesUpload(Array.from(fileInput.files));
    fileInput.value = "";
  };

  // Auto size node to comfortably fit content without layout clipping or stretching
  const FIXED_WIDTH = 360;
  const FIXED_HEIGHT = 640; // Exact height for header + 3x3 image grid + audio row + video row

  node.setSize([FIXED_WIDTH, FIXED_HEIGHT]);

  // Lock minimum size to prevent accidental squishing
  node.onResize = function(size) {
    size[0] = Math.max(size[0], FIXED_WIDTH);
    size[1] = Math.max(size[1], FIXED_HEIGHT);
  };
}
