import { app } from "../../../scripts/app.js";
import { manualLLMConnection } from "./llm_connection.js";
import { button, el, field, hideWidget, input, mediaURL, request, select, toggle } from "./replacement_common.js";
import { followNodeColours, mountNodePanel } from "./node_panel.js";
import { openReplacementEditor } from "./replacement_editor.js";
import { openReplacementSkill } from "./replacement_skill.js";
import { createViggleMedia } from "./viggle_media.js";
import { buildRichEditor } from "./replacement/prompt_editor.js";
import { injectStyles } from "./replacement/prompt_editor_support.js";

export function setupVigglePanel(node) {
  const widgets=Object.fromEntries(node.widgets.map(widget=>[widget.name,widget]));
  for(const name of ["config","selected_index","loop_generation"])hideWidget(widgets[name]);
  let config=JSON.parse(widgets.config.value),index=widgets.selected_index.value,planData,preview;
  let removed=false,busy=false,tab="original",editor,editorAbort,revision=0;
  const root=el("div","yton-replacement-panel vv-panel");
  const right=el("div","vv-prompt"),message=el("div","yr-status");message.setAttribute("role","status");
  const status=text=>{message.textContent=text;};
  const slot=()=>config.shared ? "shared" : String(index);
  const original=()=>config.prompts[slot()] ?? config.original;
  function commit(invalidate=false) {
    node.graph?.beforeChange();
    if(invalidate)config.optimized={};
    widgets.config.value=JSON.stringify(config);widgets.selected_index.value=index;
    node.graph?.afterChange();node.setDirtyCanvas(true,true);
  }
  const media=createViggleMedia({node,getConfig:()=>config,getIndex:()=>index,status,
    changed({video=false}={}) {if(video)index=0;commit(true);renderEditor();if(video)void refresh();else renderControls();},
    editVideo:()=>{
      if(!config.video){status("请先上传视频。");return;}
      void openReplacementEditor(config,draft=>{
        // Editing changes the source timeline, so selected local frame positions
        // are cleared instead of silently pointing at different source content.
        draft.keyframes={};
        draft.compression.fps=24;config=draft;index=0;commit(true);void refresh();renderSwitches();renderEditor();
      }).catch(error=>status(error.message));
    }});
  const heading=el("div","yr-row"),actions=el("div","yr-prompt-actions");
  const optimizeButton=button("✦ 优化",manualOptimize,"优化当前段提示词");
  actions.append(button("⚙",()=>openReplacementSkill(root,{
    endpoint:"viggle/skill",titleText:"Viggle · 提示词优化 Skill",
    steps:["把当前段视频等间隔抽取六帧，拼成 <Video 1> 的画面信息。",
      "参考图模式按上传槽位顺序提供最多四张图；关键帧模式按帧索引排序替换图，并提供准确帧号和时间。",
      "将视频拼图、实际参考图和当前段要求一起交给 LLM。手动与自动优化使用相同的 Skill。"],
  }),"设置 Viggle 提示词 Skill"),optimizeButton);
  heading.append(el("strong","","片段提示词"),actions);
  const navigation=el("div","yr-segment-nav");
  const previous=button("‹",()=>changeIndex(index-1),"上一段"),next=button("›",()=>changeIndex(index+1),"下一段");
  const current=select([],index,value=>changeIndex(Number(value)),"当前片段");
  navigation.append(previous,current,next);
  const switches=el("div","yr-switches");
  const tabs=el("div","yr-tabs");
  const originalTab=button("原始要求",()=>{tab="original";renderEditor();});
  const optimizedTab=button("本段优化",()=>{tab="optimized";renderEditor();});tabs.append(originalTab,optimizedTab);
  const toolbar=el("div","yr-prompt-toolbar");
  const reference=button("@ 引用",()=>{editor?.focus();editor?.showAliasMenu();}),dialogue=button("# 对白",()=>editor?.insertDialogue());
  for(const control of [reference,dialogue])control.addEventListener("pointerdown",event=>event.preventDefault());
  toolbar.append(reference,dialogue,button("抽帧预览",previewFrames));
  const editorHost=el("div","vv-editor-host"),scope=el("div","vv-scope yr-muted");
  const controls=el("div","vv-controls");
  right.append(heading,navigation,switches,tabs,toolbar,editorHost,scope,controls);
  root.append(media.root,right,message);
  root.addEventListener("pointerdown",event=>event.stopPropagation());
  root.addEventListener("keydown",event=>event.stopPropagation());
  root.addEventListener("wheel",event=>event.stopPropagation());
  followNodeColours(node,root);injectStyles();
  mountNodePanel(node,"Viggle 人物替换面板",root,780,740,{fitHeight:true});
  root.parentElement.style.overflow="visible";
  const assets=()=>{
    const result=config.video ? [{kind:"video",alias:"视频",nativeLabel:"<Video 1>",previewUrl:mediaURL(config.video)}] : [];
    const files=config.mode==="reference" ? config.images.map((name,i)=>({name,slot:i+1})).filter(item=>item.name)
      : [...(config.keyframes[String(index)]||[])].sort((a,b)=>a.frame-b.frame).filter(item=>item.image).map((item,i)=>({name:item.image,slot:i+1}));
    files.forEach((item,i)=>result.push({kind:"image",alias:`图片${item.slot}`,nativeLabel:`<Picture ${i+1}>`,previewUrl:mediaURL(item.name)}));
    return result;
  };
  function renderEditor() {
    editorAbort?.abort();editor?.dispose();editorAbort=new AbortController();
    const value=tab==="original" ? original() : config.optimized[slot()]?.text || "";
    editor=buildRichEditor({initialText:value,assets:assets(),ownerGraph:node.graph,resolveLabels:true,signal:editorAbort.signal,
      onInput:text=>{
        if(tab==="original"){config.prompts[slot()]=text;delete config.optimized[slot()];}
        else if(config.optimized[slot()])config.optimized[slot()].text=text;
        commit();
      }});
    editor.editor.setAttribute("aria-label",tab==="original"?"Viggle 原始要求":"Viggle 优化提示词");
    editor.editor.dataset.placeholder=tab==="original"?"描述谁替换谁，输入 @ 引用图片":"点击优化生成本段提示词";
    editor.editor.contentEditable=String(tab==="original" || !!config.optimized[slot()]);
    editorHost.replaceChildren(editor.editor);
    originalTab.classList.toggle("active",tab==="original");optimizedTab.classList.toggle("active",tab==="optimized");
    scope.textContent=`${config.shared?"全段共用":"按片段独立保存"} · ${config.mode==="keyframe"?"关键帧模式":"参考图模式"}`;
  }
  function renderSwitches() {
    switches.replaceChildren(toggle("全段共用提示词",config.shared,value=>{config.shared=value;commit();renderEditor();}),
      toggle("每段自动优化",config.auto,value=>{config.auto=value;commit();}),
      toggle("从当前段循环到尾",widgets.loop_generation.value,value=>{widgets.loop_generation.value=value;commit();}));
  }
  function renderControls() {
    controls.replaceChildren(el("strong","","视频与生成配置"));
    const row=(label,child)=>{const wrapper=el("div","yr-option-row");wrapper.append(el("span","yr-label",label),child);return wrapper;};
    const choices=(options,selected,change)=>{
      const group=el("div","yr-options");
      for(const [value,label] of options){const control=button(label,()=>change(value));control.setAttribute("aria-pressed",String(value===selected));group.append(control);}return group;
    };
    controls.append(row("分辨率",choices([["480p","480p"],["720p","720p"]],config.resolution,value=>{config.resolution=value;commit(true);void refresh();})),
      row("画面比例",choices([["原视频","原比例"],["9:16","9:16"],["16:9","16:9"]],config.ratio,value=>{config.ratio=value;commit(true);void refresh();})),
      row("图片缩放",select([{value:.5,label:"0.5×"},{value:.75,label:"0.75×"},{value:1,label:"1× · 原尺寸"}],config.image_scale,value=>{config.image_scale=Number(value);commit(true);},"图片缩放")),
      row("分段上下文",el("div","vv-value",planData?.plan.context_frames ? `${planData.plan.context_frames} 帧` : "无上下文")));
    const raw=preview?.frames || 0,overlap=preview?.segment.overlap_frames || 0;
    for(const [label,text] of [["原片段",raw?`${raw} 帧${overlap?` · 含重叠 ${overlap} 帧`:""}`:"—"],
      ["有效内容",raw?`${raw-overlap} 帧 · ${((raw-overlap)/24).toFixed(3)} 秒`:"—"]])controls.append(row(label,el("div","vv-value",text)));
  }
  function renderPosition() {
    const segments=planData?.plan.segments || [];
    current.replaceChildren(...(segments.length?segments.map((segment,i)=>{
      const option=el("option","",`第 ${i+1} / ${segments.length} 段 · ${(segment.start/24).toFixed(2)}–${(segment.end/24).toFixed(2)}s`);option.value=i;return option;
    }):[el("option","","待加载视频")]));
    current.value=String(index);current.disabled=!segments.length || busy;
    previous.disabled=index===0 || busy;next.disabled=index>=segments.length-1 || busy;
  }
  async function changeIndex(value) {
    index=Math.max(0,Math.min((planData?.plan.segments.length||1)-1,value));commit();renderPosition();renderEditor();await refresh();
  }
  async function refresh() {
    const token=++revision;
    if(!config.video){planData=null;preview=null;media.setPreview(null);renderPosition();renderControls();return;}
    try {
      const data=await request("viggle/plan",config);
      if(removed||token!==revision)return;
      planData=data;index=Math.min(index,data.plan.segments.length-1);commit();renderPosition();
      const value=await request("viggle/preview",{config,index});
      if(removed||token!==revision)return;
      preview=value;media.setPreview(value);renderControls();renderEditor();status("");
    } catch(error){if(token===revision&&!removed)status(error.message);}
  }
  async function manualOptimize() {
    if(busy)return;busy=true;optimizeButton.disabled=true;renderPosition();status("正在抽帧并优化…");
    try {
      if(!config.video)throw new Error("请先上传视频。");
      const connection=await manualLLMConnection(node);
      const snapshot=JSON.stringify(config),target=index,key=slot();
      const data=await request("viggle/optimize",{config,index,connection});
      if(removed)return;
      if(JSON.stringify(config)!==snapshot||target!==index)throw new Error("配置已改变，请重新优化。");
      config.optimized[key]=data;tab="optimized";commit();renderEditor();status("");
    } catch(error){status(error.message);}
    finally{busy=false;optimizeButton.disabled=false;renderPosition();}
  }
  async function previewFrames() {
    try {
      const data=await request("viggle/frames",{config,index});
      const dialog=el("dialog","yr-frames-dialog"),header=el("header","yr-row");
      header.append(el("strong","","当前段 · 视频抽帧"),button("关闭",()=>dialog.close()));
      const image=el("img");image.src=mediaURL(data.image);image.alt="当前段六帧拼图";
      dialog.append(header,image);document.body.append(dialog);dialog.showModal();dialog.addEventListener("close",()=>dialog.remove(),{once:true});
    } catch(error){status(error.message);}
  }
  const configure=node.onConfigure;
  node.onConfigure=function(){configure?.apply(this,arguments);config=JSON.parse(widgets.config.value);index=widgets.selected_index.value;renderSwitches();renderEditor();void refresh();};
  const executed=node.onExecuted;
  node.onExecuted=function(data){executed?.apply(this,arguments);const value=data.viggle_prompt?.[0];if(!value)return;index=value.index;if(config.auto){config.optimized[value.slot]={text:value.text,signature:value.signature};tab="optimized";}commit();renderEditor();void refresh();};
  const remove=node.onRemoved;
  node.onRemoved=function(){removed=true;revision++;editorAbort?.abort();editor?.dispose();media.dispose();return remove?.apply(this,arguments);};
  media.render();renderSwitches();renderControls();renderEditor();void refresh();
  return {root,media};
}
