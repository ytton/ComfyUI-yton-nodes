// Inject the current organized workflow at __WORKFLOW__ and run in an isolated page.
async (page) => {
  const p=page.context().browser().contexts().at(-1).pages()[0];
  return p.evaluate(async source=>{
    const app=window.comfyAPI.app.app;
    const data=structuredClone(source), definitions=new Map(data.definitions.subgraphs.map(s=>[s.id,s]));
    const module=key=>data.nodes.find(n=>n.properties.h3_layout_module===key);
    let nextId=Math.max(data.last_node_id,...data.nodes.map(n=>Number(n.id)))+1;
    let nextLink=Math.max(data.last_link_id,...data.definitions.subgraphs.map(s=>s.state.lastLinkId))+1;
    const link=(graph,source,output,target,input,type)=>{
      const id=nextLink++;
      graph.links.push(graph===data?[id,source,output,target,input,type]:
        {id,origin_id:source,origin_slot:output,target_id:target,target_slot:input,type});
      return id;
    };
    const template=(type,values={})=>{
      const n=LiteGraph.createNode(type);
      if(!n)throw new Error(`Missing ${type}`);
      for(const w of n.widgets??[])if(w.name in values){w.value=values[w.name];w.callback?.(w.value);}
      const record=n.serialize();record.widgets_values_named=values;
      for(const i of record.inputs??[])i.link=null;
      for(const o of record.outputs??[])o.links=[];
      return record;
    };
    const sync=graph=>{
      const nodes=new Map(graph.nodes.map(n=>[String(n.id),n]));
      for(const n of graph.nodes){for(const i of n.inputs??[])i.link=null;for(const o of n.outputs??[])o.links=[];}
      for(const p of [...graph.inputs??[],...graph.outputs??[]])p.linkIds=[];
      for(const item of graph.links){
        const l=Array.isArray(item)?{id:item[0],origin_id:item[1],origin_slot:item[2],target_id:item[3],target_slot:item[4]}:item;
        if(l.origin_id===-10)graph.inputs[l.origin_slot].linkIds.push(l.id);
        else nodes.get(String(l.origin_id)).outputs[l.origin_slot].links.push(l.id);
        if(l.target_id===-20)graph.outputs[l.target_slot].linkIds.push(l.id);
        else nodes.get(String(l.target_id)).inputs[l.target_slot].link=l.id;
      }
    };
    const addInput=(host,graph,name,label,type,targets)=>{
      const slot=graph.inputs.length;
      const port={id:crypto.randomUUID(),name,label,type,linkIds:[],pos:[276,174+slot*24]};
      graph.inputs.push(port);host.inputs.push({name,label,type,link:null});
      for(const [nodeId,inputName]of targets){
        const node=graph.nodes.find(n=>Number(n.id)===nodeId);
        const input=node.inputs.findIndex(i=>i.name===inputName);
        if(input<0)throw new Error(`No ${nodeId}.${inputName}`);
        port.linkIds.push(link(graph,-10,slot,node.id,input,type));
      }
      return slot;
    };
    const pruneInputs=(host,graph)=>{
      sync(graph);
      const map=new Map(),keep=graph.inputs.map((p,i)=>p.linkIds.length?i:null).filter(i=>i!==null);
      keep.forEach((old,index)=>map.set(old,index));
      data.links=data.links.filter(l=>String(l[3])!==String(host.id)||map.has(l[4]));
      for(const l of data.links)if(String(l[3])===String(host.id))l[4]=map.get(l[4]);
      for(const l of graph.links)if(l.origin_id===-10)l.origin_slot=map.get(l.origin_slot);
      graph.inputs=keep.map(i=>graph.inputs[i]);host.inputs=keep.map(i=>host.inputs[i]);
      graph.inputs.forEach((p,i)=>{p.pos=[276,174+i*24];});
      return graph.inputs.findIndex(p=>p.name==='assets');
    };
    // One collection replaces three separate registration nodes and four duplicate cables.
    const oldAssets=module('assets');
    const assets=template('YtonH3ReferenceAssets');
    Object.assign(assets,{id:oldAssets.id,title:'参考素材集合 · 连线后自动增加入口',pos:[770,1610],size:[330,190],
      properties:{...assets.properties,h3_layout_key:'639',h3_layout_module:'assets'},color:'#322',bgcolor:'#533'});
    // Saved autogrow sockets are reconstructed by name when the frontend loads.
    assets.inputs.push({name:'images.参考图 1',type:'IMAGE',link:null},{name:'images.参考图 2',type:'IMAGE',link:null});
    data.nodes[data.nodes.indexOf(oldAssets)]=assets;
    data.links=data.links.filter(l=>Number(l[3])!==Number(assets.id));
    for(const [id,output,name]of [[518,0,'images.参考图 1'],[495,0,'images.参考图 2'],[588,0,'video_frames'],[588,1,'video_audio']]){
      link(data,id,output,assets.id,assets.inputs.findIndex(i=>i.name===name),name==='video_audio'?'AUDIO':'IMAGE');
    }
    const conditionHost=module('conditions'), conditions=definitions.get(conditionHost.type);
    for(const id of [550,609]){
      const old=conditions.nodes.find(n=>Number(n.id)===id);
      const replacement=template('YtonH3ReferenceFromAssets',old.widgets_values_named);
      Object.assign(replacement,{id:old.id,title:id===550?'首采参考编码 · 共享素材':'二采参考编码 · 共享素材',
        pos:old.pos,size:[440,300],properties:{...replacement.properties,h3_layout_key:String(id)},color:old.color,bgcolor:old.bgcolor});
      conditions.links=conditions.links.filter(l=>{
        if(Number(l.target_id)!==id)return true;
        const name=old.inputs[l.target_slot].name;
        const slot=replacement.inputs.findIndex(i=>i.name===name);
        if(slot<0)return false;
        l.target_slot=slot;return true;
      });
      conditions.nodes[conditions.nodes.indexOf(old)]=replacement;
    }
    addInput(conditionHost,conditions,'assets','参考素材集合','H3_PGS_ASSETS',[[550,'assets'],[609,'assets']]);
    const conditionSlot=pruneInputs(conditionHost,conditions);
    link(data,assets.id,0,conditionHost.id,conditionSlot,'H3_PGS_ASSETS');
    const faceHost=module('face'),faceGraph=definitions.get(faceHost.type);
    const face=faceGraph.nodes.find(n=>Number(n.id)===618);
    const oldRef=face.inputs.findIndex(i=>i.name.startsWith('references.'));
    faceGraph.links=faceGraph.links.filter(l=>Number(l.target_id)!==618||l.target_slot!==oldRef);
    face.inputs.push({name:'assets',type:'H3_PGS_ASSETS',link:null});
    addInput(faceHost,faceGraph,'assets','参考素材集合','H3_PGS_ASSETS',[[618,'assets']]);
    const faceSlot=pruneInputs(faceHost,faceGraph);
    link(data,assets.id,0,faceHost.id,faceSlot,'H3_PGS_ASSETS');
    // Share one FLOAT value between both 32-aligned dimension expressions.
    const sizeHost=module('size'),sizeGraph=definitions.get(sizeHost.type);
    for(const n of sizeGraph.nodes){
      n.title=Number(n.id)===602?'首采宽度 · 最终宽度 × 首采比例':'首采高度 · 最终高度 × 首采比例';
      n.widgets_values=['max(32, floor(a * b / 32) * 32)'];
      n.widgets_values_named={expression:n.widgets_values[0]};
      if(!n.inputs.some(i=>i.name==='values.b'))n.inputs.push({name:'values.b',type:'FLOAT,INT,BOOLEAN',link:null});
    }
    const scaleSlot=addInput(sizeHost,sizeGraph,'first_pass_scale','首采比例','FLOAT',[[602,'values.b'],[603,'values.b']]);
    const scale=template('PrimitiveFloat',{value:.5});scale.id=nextId++;
    scale.title='首采比例 · 宽高缩放';scale.pos=[1130,1600];scale.size=[330,100];
    scale.properties={...scale.properties,h3_layout_key:String(scale.id),h3_layout_module:'scale'};
    data.nodes.push(scale);link(data,scale.id,0,sizeHost.id,scaleSlot,'FLOAT');
    sizeHost.title='首采尺寸 · 根据比例计算';sizeHost.pos=[1130,1770];sizeHost.size=[330,155];
    sizeGraph.name='首采尺寸 · 根据比例计算';
    data.nodes.find(n=>Number(n.id)===601).title='最终分辨率';
    data.nodes.find(n=>Number(n.id)===518).title='参考图 1 · <Picture 1>';
    data.nodes.find(n=>Number(n.id)===495).title='参考图 2 · <Picture 2> · 可断开';
    const note=data.nodes.find(n=>Number(n.id)===619);
    note.widgets_values=['# 灵活参考素材与首采比例\n\n参考图按【参考素材集合】的入口顺序对应 <Picture N>，不固定人物或场景用途。连接一张后自动出现下一个入口；没有场景替换就不接场景图。\n\n可复制下方任意参考图加载器，连接到集合的新入口。首采、二采、修脸和提示词编辑共用同一顺序；增删参考后同步检查提示词里的编号。\n\n首采比例在分辨率下方调整，0.5 代表首采宽高各取最终尺寸的一半；尺寸按 32 对齐，最终输出分辨率保持由分辨率控件决定。\n\n修脸人数独立控制需要修复的检测目标数，不代表参考图片数量。双击生成子流仍可替换内部节点。'];
    note.widgets_values_named={text:note.widgets_values[0]};
    for(const graph of [data,...data.definitions.subgraphs])sync(graph);
    const used=new Set(data.nodes.map(n=>n.type));
    data.definitions.subgraphs=data.definitions.subgraphs.filter(s=>used.has(s.id));
    data.last_node_id=nextId;data.last_link_id=nextLink;
    for(const s of data.definitions.subgraphs){s.state.lastLinkId=nextLink;
      s.inputNode.bounding[3]=Math.max(150,s.inputs.length*24+50);}
    data.extra.h3_flexible_references=true;
    await app.loadGraphData(data);
    // Canonicalize rebuilt autogrow sockets, then reload the exact deliverable again.
    const workflow=app.graph.serialize();
    await app.loadGraphData(workflow);
    const prompt=(await app.graphToPrompt()).output;
    window.h3FlexibleResult={workflow,prompt};
    return {nodes:workflow.nodes.length,subgraphs:workflow.definitions.subgraphs.length,
      assets:app.graph.getNodeById(String(assets.id)).inputs.map(i=>i.name),
      scale:scale.id,rootIds:workflow.nodes.map(n=>({id:n.id,title:n.title,type:n.type}))};
  },__WORKFLOW__);
}
