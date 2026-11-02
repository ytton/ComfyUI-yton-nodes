import { app } from "../../scripts/app.js";
import { button, el, field, hideWidget, input, mediaURL, request, select, toggle } from "./js/replacement_common.js";
import { mountNodePanel, followNodeColours } from "./js/node_panel.js";
import { availableModels, settingsEvents } from "./js/prompt_optimizer_api.js";
import { openOptimizerSettings } from "./js/prompt_optimizer_settings.js";
import { setupReplacementPanel } from "./js/replacement_panel.js";

for(const path of ["css/replacement.css","css/prompt_optimizer.css"]) {
  const link=document.createElement("link");link.rel="stylesheet";link.href=new URL(path,import.meta.url).href;document.head.append(link);
}

function setupConnector(node) {
  const widget=node.widgets.find(w=>w.name==="model_ref");hideWidget(widget);
  const temperature=node.widgets.find(w=>w.name==="temperature"),tokens=node.widgets.find(w=>w.name==="max_tokens");
  hideWidget(temperature);hideWidget(tokens);
  const root=el("div","yton-replacement-panel yr-connector");
  const models=el("div");
  const defaults=el("details","yr-llm-defaults");
  defaults.append(el("summary","","默认调用参数"));
  const parameters=el("div","yr-fields");
  const temperatureInput=input(temperature.value,v=>temperature.value=v,{min:0,max:2,step:.05,label:"默认温度"});
  const tokensInput=input(tokens.value,v=>tokens.value=v,{min:128,max:131072,step:128,label:"最大输出长度"});
  parameters.append(field("温度",temperatureInput),field("最大输出长度",tokensInput));defaults.append(parameters);
  root.append(models,defaults,button("⚙ 服务与模型",()=>openOptimizerSettings((path,body)=>request(`llm/${path}`,body))));
  const lifetime=new AbortController();
  async function refresh() {
    try {
      const settings=await request("llm/settings");
      const choices=[{value:"",label:"使用默认模型"},...availableModels(settings)];
      models.replaceChildren(field("模型",select(choices,widget.value,v=>{widget.value=v;node.setDirtyCanvas(true,true);},"LLM 模型")));
    } catch(error) {models.textContent=error.message;}
  }
  settingsEvents.addEventListener("change",refresh,{signal:lifetime.signal});
  const configured=node.onConfigure;
  node.onConfigure=function(){configured?.apply(this,arguments);temperatureInput.value=temperature.value;tokensInput.value=tokens.value;void refresh();};
  const removed=node.onRemoved;
  node.onRemoved=function(){lifetime.abort();return removed?.apply(this,arguments);};
  followNodeColours(node,root);mountNodePanel(node,"LLM 服务",root,310,92,{fitHeight:true});root.parentElement.style.overflow="hidden";void refresh();
}

function setupSegment(node) {
  const executed=node.onExecuted;
  node.onExecuted=function(data) {
    executed?.apply(this,arguments);
    const link=node.graph?.links[node.inputs.find(input=>input.name==="plan")?.link];
    const planner=link && node.graph.getNodeById(link.origin_id);
    if(planner?.type==="YtonReplacementPlan") planner.onExecuted?.(data);
  };
}

function setupSave(node) {
  const root=el("div","yton-replacement-panel yr-save");
  const video=el("video");video.controls=true;video.preload="metadata";video.hidden=true;
  const state=el("div","yr-status","等待循环输出片段");
  const heading=el("div","yr-save-heading");
  const back=button("",()=>{
    const merged=node.properties.replacementPreview?.merged;
    if(merged){video.src=mediaURL(merged);video.play().catch(()=>{});}
  },"返回完整视频");
  back.classList.add("yr-save-return");back.hidden=true;
  back.innerHTML='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 4-5 5 5 5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/></svg>';
  heading.append(state,back);
  const clips=el("div","yr-saved-clips");
  const controls=el("div","yr-config-controls");
  const widgets=new Map(node.widgets.map(w=>[w.name,w]));
  for(const name of ["filename_prefix","container","fps","crf","save_full"]) hideWidget(widgets.get(name));
  function change(name,value) {widgets.get(name).value=value;node.setDirtyCanvas(true,true);}
  function renderControls() {
    const row=el("div","yr-fields");
    row.append(field("格式 · H.264",select(["mp4","mkv"],widgets.get("container").value,v=>change("container",v),"保存视频格式")),
      field("帧率",input(widgets.get("fps").value,v=>change("fps",v),{min:1,max:120,step:1,label:"保存视频帧率"})),
      field("质量 CRF",input(widgets.get("crf").value,v=>change("crf",v),{min:0,max:51,step:1,label:"保存视频质量 CRF"})));
    controls.replaceChildren(field("保存目录 / 前缀",input(widgets.get("filename_prefix").value,v=>change("filename_prefix",v),{type:"text",label:"保存目录与前缀"})),row,
      toggle("保存完整视频",widgets.get("save_full").value,v=>change("save_full",v)));
  }
  root.append(video,heading,clips,controls);renderControls();
  followNodeColours(node,root);mountNodePanel(node,"循环预览",root,430,285,{fitHeight:true});root.parentElement.style.overflow="hidden";
  function render(data) {
    state.textContent=data.complete ? `已完成 ${data.total} 段 · 完整视频可播放` : `已保存 ${data.segments.length} / ${data.total} 段`;
    back.hidden=!data.merged;
    const current=data.merged || data.segments.at(-1);
    if(current) {video.src=mediaURL(current);video.hidden=false;}
    clips.replaceChildren(...data.segments.map((segment,i)=>{
      const item=button(`片段 ${i+1}`,()=>{video.src=mediaURL(segment);video.play().catch(()=>{});});
      const thumbnail=el("video");thumbnail.src=mediaURL(segment);thumbnail.muted=true;thumbnail.preload="metadata";
      item.prepend(thumbnail);return item;
    }));
  }
  const executed=node.onExecuted;
  node.onExecuted=function(data){executed?.apply(this,arguments);const saved=data.replacement_saved?.[0];if(saved){node.properties.replacementPreview=saved;render(saved);}};
  const configured=node.onConfigure;
  node.onConfigure=function(){configured?.apply(this,arguments);renderControls();if(node.properties.replacementPreview)render(node.properties.replacementPreview);};
  const removed=node.onRemoved;
  node.onRemoved=function(){root.querySelectorAll("video").forEach(v=>{v.pause();v.removeAttribute("src");v.load();});return removed?.apply(this,arguments);};
}

app.registerExtension({
  name:"yton.character-replacement",
  async beforeRegisterNodeDef(nodeType,nodeData) {
    const setup={YtonLLMConnector:setupConnector,YtonCharacterReplacement:setupReplacementPanel,YtonReplacementPlan:setupReplacementPanel,YtonReplacementSegment:setupSegment,YtonReplacementVideoSave:setupSave}[nodeData.name];
    if(!setup) return;
    const created=nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated=function(){created?.apply(this,arguments);void setup(this);};
  },
});
