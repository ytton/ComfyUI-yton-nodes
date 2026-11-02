import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { followNodeColours, mountNodePanel } from "./node_panel.js";
import { button, el, field, hideWidget, input, mediaURL, request, select, toggle } from "./replacement_common.js";
import { openReplacementEditor } from "./replacement_editor.js";

const kind = file => file.type.startsWith("video/") || /\.(mp4|webm|mov|mkv|avi|m4v)$/i.test(file.name) ? "video"
  : file.type.startsWith("image/") || /\.(png|jpe?g|webp|gif|bmp|avif)$/i.test(file.name) ? "image" : null;

export async function setupReplacementPanel(node) {
  const configWidget = node.widgets.find(w => w.name === "config");
  hideWidget(configWidget);
  let config = JSON.parse(configWidget.value), index = 0, result;
  let activeImage = -1, busy = false, removed = false, tab = "original", editor;
  let richMode = true, plainEditor;
  let editorAbort, planRevision = 0;
  const lifetime = new AbortController();
  const root = el("div", "yton-replacement-panel");
  const left = el("div", "yr-media");
  const right = el("div", "yr-prompt");
  const message = el("div", "yr-status");
  message.setAttribute("role", "status");
  const videoSlot = el("div", "yr-video-slot");
  const imageGrid = el("div", "yr-image-grid");
  const heading = el("div", "yr-row");
  const current = el("select", "yr-input yr-current");
  current.setAttribute("aria-label", "查看片段提示词");
  current.addEventListener("change", () => changeIndex(Number(current.value)));
  const previous = button("‹", () => changeIndex(index-1), "上一段");
  const next = button("›", () => changeIndex(index+1), "下一段");
  const optimizeButton = button("✦ 优化", manualOptimize, "使用当前段抽帧和参考图片优化提示词");
  heading.append(el("strong", "", "片段提示词"), optimizeButton);
  const navigation = el("div", "yr-segment-nav");
  navigation.append(previous, current, next);
  const switches = el("div", "yr-switches");
  const tabs = el("div", "yr-tabs");
  const originalTab = button("原始要求", () => {tab="original"; renderEditor();});
  const optimizedTab = button("本段优化", () => {tab="optimized"; renderEditor();});
  const promptScope = el("span", "yr-muted");
  tabs.append(originalTab, optimizedTab, promptScope);
  const editorHost = el("div", "yr-rich-host");
  const referenceButton = button("@ 引用", () => {editor?.focus();editor?.showAliasMenu();}, "插入参考素材引用");
  const dialogueButton = button("# 对白", () => editor?.insertDialogue(), "给选中文字添加对白标签");
  for(const control of [referenceButton,dialogueButton]) control.addEventListener("pointerdown", event=>event.preventDefault());
  const modeButton = button("纯文本", () => {richMode=!richMode;renderEditor();}, "切换纯文本与富文本");
  const framesButton = button("抽帧预览", previewFrames, "预览当前段送给 LLM 的抽帧拼图");
  const toolbar = el("div", "yr-prompt-toolbar");
  toolbar.append(referenceButton, dialogueButton, modeButton, framesButton);
  const controls = el("div", "yr-config-controls");
  const promptStatus = el("div", "yr-muted yr-prompt-status");
  right.append(heading, navigation, switches, tabs, toolbar, editorHost, promptStatus);
  left.append(videoSlot,el("div","yr-muted","参考图片 · 3 × 2"),imageGrid,controls,
    el("div","yr-upload-hint","拖拽、Ctrl + V 或点击上传；选中图片槽可替换该图片。"));
  root.append(left, right, message);
  root.addEventListener("pointerdown", event => event.stopPropagation());
  root.addEventListener("keydown", event => event.stopPropagation());
  followNodeColours(node, root);
  mountNodePanel(node, "人物替换面板", root, 780, 660, {fitHeight:true});
  const mediaOffset = Math.max(0, node.outputs.length - node.inputs.filter(input => !input.widget).length) * LiteGraph.NODE_SLOT_HEIGHT;
  root.style.setProperty("--yr-media-offset", `${mediaOffset}px`);
  root.parentElement.style.overflow = "visible";
  const slotKey = () => config.shared ? "shared" : String(index);
  const original = () => config.prompts[slotKey()] ?? config.original;

  function commit({invalidate = false} = {}) {
    if (invalidate) config.optimized = {};
    node.graph?.beforeChange();
    configWidget.value = JSON.stringify(config);
    node.graph?.afterChange();
    node.setDirtyCanvas(true,true);
  }
  function changeIndex(value) {
    const total = result?.plan.segments.length || 1;
    index = Math.max(0,Math.min(total-1, value));
    renderPosition(); renderEditor();
  }
  function renderPosition() {
    const total = result?.plan.segments.length || 0;
    current.replaceChildren(...(total ? result.plan.segments.map((segment,i)=>{
      const option=el("option","",`第 ${i+1} / ${total} 段 · ${(segment.start/24).toFixed(2)}–${(segment.end/24).toFixed(2)}s`);
      option.value=i;return option;
    }) : [el("option","","待加载视频")]));
    current.value=String(index);current.disabled=!total || busy;
    previous.disabled = index <= 0 || busy;
    next.disabled = index >= total-1 || busy;
    renderControls();
  }
  async function updatePlan() {
    const revision=++planRevision;
    if (!config.video) {result=null; renderPosition(); return;}
    try {
      const data = await request("replacement/plan", config);
      if (revision !== planRevision || removed) return;
      result=data;
      index=Math.max(0, Math.min(index, data.plan.segments.length-1));
      renderPosition(); message.textContent="";
    } catch(error) {if (revision===planRevision) message.textContent=error.message;}
  }
  function choose(accept, files) {
    const picker=el("input"); picker.type="file"; picker.accept=accept; picker.multiple=accept.startsWith("image");
    picker.addEventListener("change", () => files(Array.from(picker.files || [])), {once:true});
    picker.click();
  }
  let pendingUploads=Promise.resolve();
  function upload(files,preferred=-1) {
    pendingUploads=pendingUploads.then(()=>performUpload(files,preferred));
    return pendingUploads;
  }
  async function performUpload(files, preferred = -1) {
    if (busy) return;
    busy=true; optimizeButton.disabled=true; message.textContent="正在上传素材…";
    let imageIndex=preferred, notices=[];
    try {
      for (const file of files) {
        const type=kind(file);
        if (!type) {notices.push(`不支持：${file.name}`); continue;}
        if (type==="image") {
          if (imageIndex<0) imageIndex=config.images.findIndex(v=>!v);
          if (imageIndex<0 || imageIndex>=6) {notices.push("六个图片槽位已满"); continue;}
        }
        const body=new FormData(); body.append("image",file); body.append("type","input"); body.append("subfolder","yton-replacement");
        const response=await api.fetchApi("/upload/image", {method:"POST",body});
        if (!response.ok) throw new Error(`上传失败（${response.status}）`);
        const data=await response.json();
        if (!data.name) throw new Error("上传没有返回文件名");
        const filename=[data.subfolder,data.name].filter(Boolean).join("/");
        if (removed) return;
        if (type==="video") config.video=filename;
        else {config.images[imageIndex]=filename; imageIndex++; while(imageIndex<6 && config.images[imageIndex]) imageIndex++;}
      }
      commit({invalidate:true}); renderMedia(); renderEditor(); await updatePlan();
      message.textContent=notices.join("；");
    } catch(error) {message.textContent=error.message;}
    finally {busy=false; optimizeButton.disabled=false; renderPosition();}
  }
  function renderMedia() {
    videoSlot.replaceChildren(); imageGrid.replaceChildren();
    const top=el("div","yr-slot-toolbar");
    top.append(el("b","","Video 1"), button("编辑", () => {
      if (!config.video) {message.textContent="请先上传视频。"; return;}
      void openReplacementEditor(config, draft => {
        config=draft; commit({invalidate:true}); renderAll(); void updatePlan();
      }).catch(error=>{message.textContent=`视频编辑器加载失败：${error.message}`;});
    }));
    videoSlot.append(top);
    if (config.video) {
      const video=el("video"); video.src=mediaURL(config.video); video.controls=true; video.preload="metadata";
      videoSlot.append(video);
      top.append(button("×",()=>{config.video="";commit({invalidate:true});renderAll();updatePlan();},"移除视频"));
    } else videoSlot.append(button("＋ 拖入、粘贴或选择视频",()=>choose("video/*",files=>upload(files))));
    const fileRow=el("div","yr-file-row");
    const filename=el("span","yr-muted",config.video.split("/").at(-1) || "未选择视频");filename.title=config.video;
    fileRow.append(filename,button("上传 / 替换",()=>choose("video/*",files=>upload(files)),"选择视频文件"));
    videoSlot.append(fileRow);
    const dropHint=el("div","yr-video-drop-hint");
    dropHint.setAttribute("aria-hidden","true");
    dropHint.append(el("span","","↓"),el("strong","",config.video ? "松开替换视频" : "松开上传视频"));
    videoSlot.append(dropHint);
    let nativeIndex=0;
    config.images.forEach((filename,i)=>{
      const card=el("div",`yr-image-slot${activeImage===i ? " selected" : ""}`);
      card.dataset.slot=String(i);
      card.tabIndex=0;
      const label=filename ? `Picture ${++nativeIndex}` : `图片 ${i+1}`;
      card.setAttribute("aria-label",`${label}，点击选择，双击上传`);
      card.addEventListener("click",()=>{activeImage=i; imageGrid.querySelectorAll(".yr-image-slot").forEach((c,n)=>c.classList.toggle("selected",n===i));});
      card.addEventListener("dblclick",()=>choose("image/*",files=>upload(files,i)));
      card.addEventListener("keydown",event=>{if(event.key==="Enter") choose("image/*",files=>upload(files,i));});
      if (filename) {const img=el("img"); img.src=mediaURL(filename); img.alt=label; card.append(img);}
      const uploadButton=button("↥",()=>choose("image/*",files=>upload(files,i)),`选择图片 ${i+1}`);
      uploadButton.classList.add("yr-image-upload");card.append(uploadButton);
      if(!filename) card.append(el("span","yr-image-empty","＋"));
      const toolbar=el("div","yr-image-toolbar");
      toolbar.append(el("span","",label));
      if (filename) toolbar.append(button("×",()=>{config.images[i]="";commit({invalidate:true});renderMedia();renderEditor();},`移除图片 ${i+1}`));
      card.append(toolbar);
      card.addEventListener("dragover",event=>{event.preventDefault();card.classList.add("drag-over");});
      card.addEventListener("dragleave",event=>{if(!card.contains(event.relatedTarget))card.classList.remove("drag-over");});
      card.addEventListener("drop",event=>{event.preventDefault();event.stopPropagation();card.classList.remove("drag-over");void upload(Array.from(event.dataTransfer.files),i);});
      imageGrid.append(card);
    });
  }
  function assets() {
    const list=[];
    if(config.video) list.push({kind:"video",alias:"视频",nativeLabel:"<Video 1>",previewUrl:mediaURL(config.video)});
    let n=0;
    config.images.forEach((name,i)=>{if(name)list.push({kind:"image",alias:`图片${i+1}`,nativeLabel:`<Picture ${++n}>`,previewUrl:mediaURL(name)});});
    return list;
  }
  let buildRichEditor, resolvePromptAliases, resolveNativeLabelsToAliases;
  async function renderEditor() {
    if (!buildRichEditor || removed) return;
    editorAbort?.abort(); editor?.dispose(); editorAbort=new AbortController();
    const optimized=config.optimized[slotKey()];
    const initial=tab==="original" ? original() : optimized?.text || "";
    const saveText=text=>{
      if(tab==="original") {config.prompts[slotKey()]=text;delete config.optimized[slotKey()];}
      else if(config.optimized[slotKey()]) config.optimized[slotKey()].text=text;
      commit();
    };
    if(!richMode) {
      editor=null;
      plainEditor=el("textarea","yr-plain-editor");
      plainEditor.value=resolvePromptAliases(initial,assets(),"Ref2VA");
      plainEditor.setAttribute("aria-label",tab==="original" ? "原始人物替换要求" : "本段优化结果");
      plainEditor.readOnly=tab==="optimized" && !optimized;
      plainEditor.addEventListener("input",()=>saveText(resolveNativeLabelsToAliases(plainEditor.value,assets(),"Ref2VA")));
      editorHost.replaceChildren(plainEditor);
    } else {
    editor=buildRichEditor({initialText:initial,assets:assets(),ownerGraph:node.graph,resolveLabels:true,signal:editorAbort.signal,
      onInput:saveText});
    editor.editor.setAttribute("aria-label",tab==="original" ? "原始人物替换要求" : "本段优化结果");
    editor.editor.dataset.placeholder=tab==="original" ? "描述人物与场景替换要求，输入 @ 引用素材" : "点击右上角优化，生成本段提示词";
    if(tab==="optimized" && !optimized) editor.editor.contentEditable="false";
    editorHost.replaceChildren(editor.editor);
    }
    originalTab.classList.toggle("active",tab==="original"); optimizedTab.classList.toggle("active",tab==="optimized");
    originalTab.setAttribute("aria-pressed",String(tab==="original"));optimizedTab.setAttribute("aria-pressed",String(tab==="optimized"));
    modeButton.textContent=richMode ? "纯文本" : "富文本";
    referenceButton.disabled=!richMode;dialogueButton.disabled=!richMode;
    promptScope.textContent=config.shared ? "全段共用" : "按片段独立保存";
    promptStatus.textContent=`${config.shared ? "所有片段共用提示词" : `第 ${index+1} 段独立保存提示词`} · ${optimized ? "输出优化内容" : "输出原始要求"}`;
  }
  function renderSwitches() {
    switches.replaceChildren(toggle("全段共用提示词",config.shared,value=>{
      const text=original(); config.shared=value;
      if(value && config.prompts.shared===undefined) config.prompts.shared=text;
      commit(); renderSwitches(); renderEditor();
    }),toggle("每段自动优化",config.auto,value=>{config.auto=value;commit();}));
  }
  function renderControls() {
    const segment=result?.plan.segments[index];
    controls.replaceChildren();
    const optionRow=(label,children)=>{const row=el("div","yr-option-row");const options=el("div","yr-options");options.append(...children);row.append(el("span","yr-label",label),options);return row;};
    const choice=(label,value,selected,change)=>{const control=button(label,()=>{change(value);commit({invalidate:true});renderControls();});control.setAttribute("aria-pressed",String(selected===value));return control;};
    const resolution=optionRow("分辨率",["480p","720p","1080p"].map(v=>choice(v,v,config.resolution,value=>{config.resolution=value;config.compression.width=0;config.compression.height=0;})));
    const duration=el("div","yr-option-row yr-duration");
    if(config.plan.enabled) {
      duration.append(el("span","yr-label","本段帧数"),button(segment ? `${segment.end-segment.start} 帧 · ${((segment.end-segment.start)/24).toFixed(3)} 秒` : "由分段计划控制",()=>videoSlot.querySelector("button").click(),"时长由分段计划决定，点击编辑计划"));
    } else {
      const custom=input([5,10,15].includes(config.plan.seconds) ? "" : config.plan.seconds,v=>{config.plan.seconds=v;commit({invalidate:true});void updatePlan();},{min:0.001,label:"自定义每段时长，支持小数"});custom.placeholder="自定义";
      const options=el("div","yr-options");
      options.append(...[5,10,15].map(v=>choice(`${v} 秒`,v,config.plan.seconds,value=>{config.plan.seconds=value;void updatePlan();})),custom);
      duration.append(el("span","yr-label","每段时长"),options);
    }
    const ratio=optionRow("画面比例",["原视频","9:16","1:1"].map(v=>{
      const control=choice(v==="原视频" ? "原比例" : v,v,config.ratio,value=>{config.ratio=value;config.compression.width=0;config.compression.height=0;});
      control.prepend(el("span",`yr-ratio ${v==="9:16" ? "tall" : v==="1:1" ? "square" : ""}`));return control;
    }));
    const scale=optionRow("图片缩放",[select([{value:.5,label:"0.5× · 最长边等比缩放"},{value:.75,label:"0.75× · 最长边等比缩放"},{value:1,label:"1× · 原尺寸"}],config.image_scale,v=>{config.image_scale=Number(v);commit({invalidate:true});},"六张图片按各自最长边等比缩放")]);
    controls.append(resolution,duration,ratio,scale);
  }
  async function previewFrames() {
    if(!config.video || busy) return;
    framesButton.disabled=true;
    try {
      const data=await request("replacement/frames",{config,index});
      const dialog=el("dialog","yr-frames-dialog");
      const heading=el("header","yr-row");heading.append(el("b","",`第 ${index+1} 段 · 优化时使用的抽帧`),button("关闭",()=>dialog.close()));
      const image=el("img");image.src=mediaURL(data.image);image.alt="当前段六帧时间顺序拼图";
      dialog.append(heading,image);document.body.append(dialog);dialog.showModal();dialog.addEventListener("close",()=>dialog.remove(),{once:true});
    } catch(error) {message.textContent=error.message;}
    finally {framesButton.disabled=false;}
  }
  async function manualOptimize() {
    if(busy) return;
    busy=true; optimizeButton.disabled=true; message.textContent="正在抽取当前段画面并优化…";
    try {
      if(!config.video) throw new Error("请先上传视频。");
      const llmInput=node.inputs.find(i=>i.name==="llm");
      const link=node.graph.links[llmInput?.link];
      if(!link) throw new Error("请先连接【LLM 通用连接器】。");
      const {output}=await app.graphToPrompt();
      const source=output[String(link.origin_id)];
      if(source?.class_type!=="YtonLLMConnector") throw new Error("手动优化需要连接【LLM 通用连接器】。");
      const connection=Object.fromEntries(["model_ref","temperature","max_tokens"].map(k=>[k,source.inputs[k]]));
      if(Object.values(connection).some(Array.isArray)) throw new Error("手动优化请在连接器中填写调用参数；参数由上游计算时请开启自动优化执行工作流。");
      const snapshot=JSON.stringify(config), target=index, slot=slotKey();
      const data=await request("replacement/optimize",{config,index,connection});
      if(removed) return;
      if(JSON.stringify(config)!==snapshot || index!==target) throw new Error("配置已改变，请重新优化当前段。");
      config.optimized[slot]=data;commit();tab="optimized";renderEditor();message.textContent="优化完成";
    } catch(error) {message.textContent=error.message;}
    finally {busy=false;optimizeButton.disabled=false;renderPosition();}
  }
  function renderAll() {renderMedia();renderSwitches();renderPosition();renderEditor();}
  function clearVideoDrag() {
    root.classList.remove("yr-drag-over");videoSlot.classList.remove("drag-over");
  }
  function dragOver(event) {
    event.preventDefault();event.stopPropagation();
    const transfer=event.dataTransfer;
    const video=Array.from(transfer?.items || []).some(item=>item.kind==="file" && item.type.startsWith("video/"))
      || Array.from(transfer?.files || []).some(file=>kind(file)==="video");
    root.classList.toggle("yr-drag-over",video);videoSlot.classList.toggle("drag-over",video);
    if(transfer) transfer.dropEffect="copy";
  }
  root.addEventListener("dragenter",dragOver);
  root.addEventListener("dragover",dragOver);
  root.addEventListener("dragleave",event=>{if(!root.contains(event.relatedTarget))clearVideoDrag();});
  document.addEventListener("drop",clearVideoDrag,{capture:true,signal:lifetime.signal});
  document.addEventListener("dragend",clearVideoDrag,{signal:lifetime.signal});
  root.addEventListener("drop",event=>{event.preventDefault();event.stopPropagation();void upload(Array.from(event.dataTransfer.files),activeImage);});
  document.addEventListener("paste",event=>{
    if(event.defaultPrevented || removed || node.graph!==app.canvas?.graph) return;
    if(event.target instanceof Element && event.target.closest("input,textarea,[contenteditable]:not([contenteditable='false'])")) return;
    const selected=Object.values(app.canvas.selected_nodes || {});
    if(selected.find(n=>n.type==="YtonCharacterReplacement")!==node) return;
    const files=Array.from(event.clipboardData?.files || []).filter(f=>kind(f));
    if(!files.length) return;
    event.preventDefault();event.stopImmediatePropagation();void upload(files,activeImage);
  },{capture:true,signal:lifetime.signal});
  const configure=node.onConfigure;
  node.onConfigure=function(){configure?.apply(this,arguments);config=JSON.parse(configWidget.value);index=0;renderAll();void updatePlan();};
  const executed=node.onExecuted;
  node.onExecuted=function(data){
    executed?.apply(this,arguments);
    const output=data.replacement_prompt?.[0];
    if(!output) return;
    index=output.index;
    if(config.auto) {config.optimized[output.slot]={text:output.text,signature:output.signature};commit();}
    tab=config.auto ? "optimized" : tab;renderPosition();renderEditor();
  };
  const remove=node.onRemoved;
  node.onRemoved=function(){removed=true;lifetime.abort();editorAbort?.abort();editor?.dispose();root.querySelectorAll("video").forEach(v=>{v.pause();v.removeAttribute("src");v.load();});return remove?.apply(this,arguments);};
  renderAll();void updatePlan();
  try {
    const [rich,utils,styles]=await Promise.all([
      import("./replacement/prompt_editor.js"),
      import("./replacement/prompt_editor_support.js"),
      import("./replacement/prompt_editor_support.js"),
    ]);
    ({buildRichEditor}=rich);({resolvePromptAliases,resolveNativeLabelsToAliases}=utils);styles.injectStyles();
    renderEditor();
  } catch(error) {message.textContent="提示词编辑器加载失败，请刷新页面并检查浏览器日志。"; console.error(error);}
}
