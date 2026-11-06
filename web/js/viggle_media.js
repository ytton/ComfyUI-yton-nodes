import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { button, el, mediaURL, request } from "./replacement_common.js";

export const mediaKind = file => file.type.startsWith("video/") || /\.(mp4|mov|webm|mkv|m4v)$/i.test(file.name) ? "video"
  : file.type.startsWith("image/") || /\.(png|jpe?g|webp|bmp|avif)$/i.test(file.name) ? "image" : null;

export function chooseFiles(accept, callback) {
  const picker = el("input");
  Object.assign(picker, {type:"file", accept, multiple:accept.startsWith("image")});
  picker.addEventListener("change", () => callback(Array.from(picker.files)), {once:true});
  picker.click();
}

export function findPreviousResult(node, index) {
  const visited = new Set(), pending = [node];
  while (pending.length) {
    const current = pending.shift();
    if (!current || visited.has(current.id)) continue;
    visited.add(current.id);
    const clips = current.properties?.replacementPreview?.segments || [];
    const result = clips.find(file => Number(file.filename.match(/^segment_(\d+)\./)?.[1]) === index);
    if (result) return result;
    for (const output of current.outputs || []) for (const id of output.links || []) {
      const link = node.graph?.links[id];
      if (link) pending.push(node.graph.getNodeById(link.target_id));
    }
  }
  return null;
}

export function createViggleMedia({node, getConfig, getIndex, changed, status, editVideo}) {
  const root = el("div", "vv-media");
  const modes = el("div", "vv-modes");
  const videoBox = el("div", "vv-video-box");
  const stage = el("div", "vv-stage");
  const video = el("video"); video.preload = "metadata"; video.playsInline = true;
  const counter = el("span", "vv-counter");
  const fileRow = el("div", "vv-file-row");
  const fileName = el("span", "yr-muted");
  fileRow.append(fileName, button("编辑 / 分段", editVideo), button("↥", () => chooseFiles("video/*", ingest), "选择视频"));
  stage.append(video, counter); videoBox.append(stage, fileRow);
  const playback = el("div", "vv-playback");
  const play = button("▶", () => video.paused ? video.play().catch(error => status(error.message)) : video.pause(), "播放 / 暂停");
  const frameLabel = el("span", "yr-muted");
  const lock = button("⚑ 锁定此帧 C", lockFrame, "锁定当前关键帧（C）");
  playback.append(play, frameLabel, lock);
  const timeline = el("div", "vv-timeline");
  const track = el("div", "vv-track");
  const overlapBand = el("div", "vv-overlap-band");
  const slider = el("input", "vv-slider");
  Object.assign(slider, {type:"range", min:0, max:0, step:1, value:0});
  slider.setAttribute("aria-label", "当前视频帧");
  const markers = el("div", "vv-markers");
  track.append(overlapBand, slider); timeline.append(track, markers);
  const heading = el("div", "vv-list-heading");
  const title = el("strong"), count = el("span", "yr-muted");
  heading.append(title, count);
  const references = el("div", "vv-references");
  const keyframes = el("div", "vv-keyframes");
  const columns = el("div", "vv-column-labels"); columns.append(el("span", "", "原帧"), el("span", "", "替换帧"));
  const pairs = el("div", "vv-pairs");
  keyframes.append(columns, pairs);
  root.append(modes, videoBox, playback, timeline, heading, references, keyframes);
  let info, frame = 0, selected = null, removed = false, uploads = Promise.resolve(), pendingFrame;
  const originals = new Map(), loading = new Set();
  const abort = new AbortController();
  const entries = () => getConfig().keyframes[String(getIndex())] || [];
  const allFrames = () => [...entries()].sort((a,b) => a.frame - b.frame);
  const thumbnail = (file, alt) => {
    const box = el("div", "vv-thumb");
    if (file) {const img = el("img"); img.src = mediaURL(file); img.alt = alt; box.append(img);}
    else {box.classList.add("vv-empty");box.append(el("span", "vv-image-symbol", "▧"));box.setAttribute("aria-label", alt);}
    return box;
  };
  function seek(value) {
    frame = Math.max(0, Math.min((info?.frames || 1) - 1, value));
    if (video.src && Number.isFinite(video.duration)) video.currentTime = frame / 24;
    updateCounter();
  }
  function updateCounter() {
    const total = info?.frames || 0;
    counter.textContent = total ? `第 ${frame+1} / ${total} 帧` : "待加载视频";
    frameLabel.textContent = `帧索引 ${frame}`;
    slider.max = Math.max(0, total - 1); slider.value = frame;
    slider.disabled = !total;
    lock.disabled = !total || entries().length >= 4 || entries().some(item => item.frame === frame);
    play.textContent = video.paused ? "▶" : "Ⅱ";
  }
  async function originalFrame(targetIndex, targetFrame) {
    const key = `${info?.video.filename}:${targetIndex}:${targetFrame}`;
    if (originals.has(key)) return originals.get(key);
    const data = await request("viggle/frame", {config:getConfig(), index:targetIndex, frame:targetFrame});
    originals.set(key, data.image);
    return data.image;
  }
  async function loadOriginal(item, box) {
    const target = getIndex(), snapshot = getConfig().video;
    try {
      const file = await originalFrame(target, item.frame);
      if (removed || snapshot !== getConfig().video || target !== getIndex() || !box.isConnected) return;
      const img = el("img");img.src = mediaURL(file);img.alt = `第${item.frame+1}帧原图`;
      box.querySelector(".vv-image-symbol")?.remove();box.prepend(img);box.classList.remove("vv-empty");
      const download = button("↓", async () => {
        try {
          const response = await fetch(mediaURL(file));
          if (!response.ok) throw new Error("下载失败，请重新加载此帧。");
          const url = URL.createObjectURL(await response.blob());
          const link = el("a");link.href = url;
          link.download = `${getConfig().video.split("/").at(-1).replace(/\.[^.]+$/, "")}_第${item.frame+1}帧.png`;
          document.body.append(link);link.click();link.remove();setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (error) {status(error.message);}
      }, `下载第${item.frame+1}帧`);
      download.classList.add("vv-download");box.append(download);
    } catch (error) {if (!removed) status(error.message);}
  }
  function selectTarget(target) {
    selected = target;
    root.querySelectorAll("[data-upload-target]").forEach(box => box.classList.toggle("selected", box.dataset.uploadTarget === `${target.kind}:${target.value}`));
  }
  function dropTarget(box, target) {
    box.dataset.uploadTarget = `${target.kind}:${target.value}`;
    box.classList.toggle("selected", selected?.kind === target.kind && selected?.value === target.value);
    box.addEventListener("click", () => selectTarget(target));
    box.addEventListener("dragover", event => {event.preventDefault();event.stopPropagation();box.classList.add("drag-over");});
    box.addEventListener("dragleave", () => box.classList.remove("drag-over"));
    box.addEventListener("drop", event => {event.preventDefault();event.stopPropagation();box.classList.remove("drag-over");selectTarget(target);void ingest(Array.from(event.dataTransfer.files), target);});
  }
  function renderMarkers() {
    markers.replaceChildren();
    overlapBand.style.width = `${100 * (info?.segment.overlap_frames || 0) / Math.max(1, info?.frames || 1)}%`;
    if (getConfig().mode !== "keyframe") return;
    for (const item of allFrames()) {
      const marker = button(String(item.frame+1), () => seek(item.frame), `跳到第${item.frame+1}帧`);
      marker.classList.add("vv-marker");marker.style.left = `${100 * item.frame / Math.max(1, (info?.frames || 1)-1)}%`;
      let dragStart, destination;
      marker.addEventListener("pointerdown", event => {event.stopPropagation();dragStart=event.clientX;destination=item.frame;marker.setPointerCapture(event.pointerId);});
      marker.addEventListener("pointermove", event => {
        if (dragStart === undefined || Math.abs(event.clientX-dragStart) < 3) return;
        const rect=track.getBoundingClientRect();destination=Math.round(Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width))*(info.frames-1));
        marker.style.left=`${100*destination/(info.frames-1)}%`;seek(destination);
      });
      marker.addEventListener("pointerup", () => {
        dragStart=undefined;
        if (destination !== item.frame && !entries().some(other => other.frame === destination)) {item.frame=destination;if(destination >= (info?.segment.overlap_frames||0))item.source="upload";selected={kind:"keyframe",value:destination};changed();render();}
        else renderMarkers();
      });
      markers.append(marker);
    }
  }
  function render() {
    const config=getConfig(), pinMode=config.mode === "keyframe";
    modes.replaceChildren(...[["reference","参考图模式"],["keyframe","关键帧模式"]].map(([value,label]) => {
      const control=button(label, () => {config.mode=value;selected=null;changed();render();});
      control.setAttribute("aria-pressed", String(config.mode===value));return control;
    }));
    references.hidden=pinMode;keyframes.hidden=!pinMode;lock.hidden=!pinMode;
    title.textContent=pinMode ? "替换关键帧" : "参考图片";
    count.textContent=`${pinMode ? entries().length : config.images.filter(Boolean).length} / 4`;
    fileName.textContent=config.video.split("/").at(-1) || "拖入或上传视频";
    references.replaceChildren();pairs.replaceChildren();
    if (!pinMode) config.images.forEach((name,i) => {
      const card=el("div", "vv-reference");
      const image=thumbnail(name,`图片 ${i+1}`);dropTarget(image,{kind:"reference",value:i});
      const footer=el("div", "vv-reference-footer");
      footer.append(el("span", "yr-muted", `图片 ${i+1}`),button("↥",()=>chooseFiles("image/*", files=>ingest(files,{kind:"reference",value:i})),`上传图片${i+1}`));
      if(name) footer.append(button("×",()=>{config.images[i]="";changed();render();},`移除图片${i+1}`));
      card.append(image,footer);references.append(card);
    });
    if (pinMode) for (const [i,item] of allFrames().entries()) {
      const row=el("div", "vv-pair");row.dataset.frame=item.frame;
      const top=el("div", "vv-pair-top"),actions=el("div", "vv-pair-actions");
      top.append(el("span", "", `第 ${item.frame+1} 帧 · 图片 ${i+1}`), actions);
      actions.append(button("↥",()=>chooseFiles("image/*", files=>ingest(files,{kind:"keyframe",value:item.frame})),`上传第${item.frame+1}帧替换图`));
      if (getIndex()>0 && item.frame<(info?.segment.overlap_frames || 0)) actions.append(button("使用重叠帧",()=>useOverlap(item),"使用上一段重叠帧"));
      actions.append(button("×",()=>{config.keyframes[String(getIndex())]=entries().filter(other=>other!==item);changed();render();},`删除第${item.frame+1}帧`));
      const images=el("div", "vv-pair-images");
      const original=thumbnail(null,`第${item.frame+1}帧原图`);original.classList.add("vv-original");
      original.append(el("span", "vv-thumb-label", "原帧"));void loadOriginal(item,original);
      const target=thumbnail(item.image,`第${item.frame+1}帧替换图片占位`);dropTarget(target,{kind:"keyframe",value:item.frame});
      if(item.image) target.append(el("span", "vv-thumb-label",item.source==="previous" ? "上一段重叠帧" : "替换帧"));
      images.append(original,target);row.append(top,images);pairs.append(row);
    }
    renderMarkers();updateCounter();
  }
  async function useOverlap(item) {
    const target=getIndex(),config=getConfig(),previous=findPreviousResult(node,target);
    if(!previous) {status("请先生成并保存上一段视频，然后点击使用重叠帧。");return;}
    try {
      const data=await request("viggle/overlap-frame", {config,index:target,frame:item.frame,previous});
      if(removed || getConfig()!==config || getIndex()!==target) return;
      item.image=`${data.image.subfolder}/${data.image.filename} [temp]`;item.source="previous";
      changed();render();status("");
    } catch(error) {status(error.message);}
  }
  function lockFrame() {
    if (!info || getConfig().mode!=="keyframe" || entries().length>=4 || entries().some(item=>item.frame===frame)) return;
    const config=getConfig();config.keyframes[String(getIndex())]??=[];
    config.keyframes[String(getIndex())].push({frame,image:"",source:"upload"});
    selected={kind:"keyframe",value:frame};changed();render();
    const chosen=pairs.querySelector(`[data-frame="${frame}"]`);
    if(chosen)pairs.scrollTo({top:Math.max(0,chosen.offsetTop-pairs.offsetTop+pairs.scrollTop+chosen.offsetHeight-pairs.clientHeight),behavior:"smooth"});
  }
  function ingest(files, target=selected) {
    const config=getConfig(),index=getIndex();
    uploads=uploads.catch(()=>{}).then(async()=>{
      let nextSlot=target?.kind==="reference" ? target.value : -1;
      for(const file of files) {
        const kind=mediaKind(file);if(!kind)continue;
        if(config!==getConfig() || index!==getIndex() || removed)return;
        let entry;
        if(kind==="image") {
          if(config.mode==="reference") {
            if(nextSlot<0)nextSlot=config.images.findIndex(name=>!name);
            if(nextSlot<0 || nextSlot>=4){status("最多上传四张参考图。");break;}
          } else {
            entry=target?.kind==="keyframe" ? entries().find(item=>item.frame===target.value) : entries().find(item=>!item.image);
            if(!entry){status("先按 C 选择关键帧，再上传替换图。");break;}
          }
        }
        const body=new FormData();body.append("image",file);body.append("type","input");body.append("subfolder","yton-viggle");
        const response=await api.fetchApi("/upload/image",{method:"POST",body});
        if(!response.ok)throw new Error(`上传失败（${response.status}）`);
        const result=await response.json();if(!result.name)throw new Error("上传没有返回文件名。");
        if(config!==getConfig() || index!==getIndex() || removed)return;
        const filename=[result.subfolder,result.name].filter(Boolean).join("/");
        if(kind==="video") {config.video=filename;config.keyframes={};info=null;changed({video:true});render();return;}
        if(config.mode==="reference") {config.images[nextSlot]=filename;nextSlot++;while(nextSlot<4&&config.images[nextSlot])nextSlot++;}
        else {entry.image=filename;entry.source="upload";target=null;}
        changed();render();status("");
      }
    }).catch(error=>status(error.message));
    return uploads;
  }
  slider.addEventListener("input",()=>seek(Number(slider.value)));
  for(const event of ["timeupdate","seeked","play","pause","loadedmetadata"])video.addEventListener(event,()=>{frame=Math.max(0,Math.min((info?.frames||1)-1,Math.floor(video.currentTime*24+.01)));updateCounter();});
  function previewTick() {if(removed||video.paused)return;updateCounter();pendingFrame=video.requestVideoFrameCallback?.((_now,metadata)=>{frame=Math.min((info?.frames||1)-1,Math.floor(metadata.mediaTime*24+.01));previewTick();});}
  video.addEventListener("play",previewTick);
  root.addEventListener("dragover",event=>{event.preventDefault();event.stopPropagation();});
  root.addEventListener("drop",event=>{event.preventDefault();event.stopPropagation();void ingest(Array.from(event.dataTransfer.files));});
  document.addEventListener("paste",event=>{
    if(event.defaultPrevented || removed || node.graph!==app.canvas?.graph || !Object.values(app.canvas?.selected_nodes||{}).includes(node))return;
    if(event.target instanceof Element && event.target.closest("input,textarea,[contenteditable='true']"))return;
    const files=Array.from(event.clipboardData?.files||[]).filter(file=>mediaKind(file));
    if(files.length){event.preventDefault();event.stopImmediatePropagation();void ingest(files);}
  },{capture:true,signal:abort.signal});
  document.addEventListener("keydown",event=>{
    if(event.key.toLowerCase()!=="c" || event.ctrlKey || event.metaKey || event.altKey || removed)return;
    if(event.target instanceof Element && event.target.closest("input,textarea,[contenteditable='true']"))return;
    if(node.graph!==app.canvas?.graph || !Object.values(app.canvas?.selected_nodes||{}).includes(node))return;
    event.preventDefault();event.stopImmediatePropagation();lockFrame();
  },{capture:true,signal:abort.signal});
  return {root,render,ingest,
    setPreview(value) {info=value;frame=0;selected=null;const url=value ? mediaURL(value.video) : "";if(video.getAttribute("src")!==url){video.pause();if(url)video.src=url;else{video.removeAttribute("src");video.load();}}render();},
    dispose() {removed=true;abort.abort();if(pendingFrame)video.cancelVideoFrameCallback?.(pendingFrame);video.pause();video.removeAttribute("src");video.load();},
  };
}
