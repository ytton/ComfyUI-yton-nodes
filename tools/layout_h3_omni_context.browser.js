// Replace __H3_CONTEXT_WORKFLOW__ with the original workflow JSON and run on an
// isolated ComfyUI page. Block prompt submissions and websocket workflow-follow.
async (page) => {
  const p = page.context().browser().contexts().at(-1).pages()[0];
  return await p.evaluate(async workflowSource => {
    const app = window.comfyAPI.app.app;
    await app.loadGraphData(workflowSource);
    const g = app.graph;
    const tag = (graph, prefix = '') => {
      for (const n of graph._nodes) {
        if (n.isSubgraphNode()) tag(n.subgraph, `${prefix}${n.id}:`);
        else n.properties.h3_layout_key = prefix + n.id;
      }
    };
    tag(g);
    const normalizedPrompt = async () => {
      const keys = {};
      const visit = (graph, prefix = '') => {
        for (const n of graph._nodes) {
          const id = prefix + n.id;
          if (n.isSubgraphNode()) visit(n.subgraph, id + ':');
          else keys[id] = n.properties.h3_layout_key;
        }
      };
      visit(g);
      const { output } = await app.graphToPrompt();
      return Object.fromEntries(Object.entries(output).map(([id, n]) => [keys[id], {
        class_type: n.class_type,
        inputs: Object.fromEntries(Object.entries(n.inputs).map(([name, value]) => [name,
          Array.isArray(value) && typeof value[1] === 'number' && keys[value[0]]
            ? [keys[value[0]], value[1]] : value]))
      }]).sort(([a], [b]) => a.localeCompare(b)));
    };
    const before = await normalizedPrompt();
    const find = id => g.getNodeById(String(id));
    const mods = {}, targetSockets = {};
    const promote = (converted, id, name, label) => {
      const inner = converted.subgraph.nodes.find(n => n.properties.h3_layout_key === String(id));
      const input = inner.inputs.find(i => i.name === name);
      if (!input) throw new Error(`Missing control ${id}.${name}`);
      const widget = inner.widgets.find(w => w.name === name);
      const value = widget.value;
      const port = converted.subgraph.addInput(name, input.type);
      port.label = label;
      port.connect(input, inner);
      const outer = converted.node.inputs.find(i => i.name === port.name);
      outer.label = label;
      // Promotion creates a native widget that retains its target node's options.
      const promoted = converted.node.widgets.find(w => w.name === name);
      if (!promoted) throw new Error(`Widget was not promoted: ${name}`);
      promoted.value = value;
    };
    const convert = (key, ids, title, controls = []) => {
      // Autogrow and dynamic-combo nodes rebuild their socket order when cloned.
      // Preserve names before conversion so native links can be remapped afterward.
      for (const n of ids.map(find)) {
        targetSockets[n.properties.h3_layout_key] = Object.fromEntries(
          n.inputs.filter(i=>i.link!=null).map(i=>[i.link,i.name]));
      }
      const converted = g._convertToSubgraphImpl(new Set(ids.map(find)));
      converted.subgraph.name = title;
      converted.node.title = title;
      converted.node.properties.h3_layout_module = key;
      mods[key] = converted.node;
      for (const control of controls) promote(converted, ...control);
      for (const [index,input] of converted.node.inputs.entries()) {
        const port = converted.subgraph.inputs[index];
        if (port) input.label = port.label || port.name;
      }
      return converted;
    };
    convert('context', [624,625,626,627,628,629,637], '上下文准备 · 尾部 22 帧');
    convert('assets', [462,463,466], '参考素材登记');
    convert('size', [602,603], '首采尺寸 · 最终宽高 × 0.5');
    convert('conditions', [460,550,609,581,630,631,611,632,633,622,623,620], '03 参考与上下文编码 · 释放 TE');
    convert('second', [606,607,608,612,613,614,615,616,617,621], '05 传统放大与二采', [
      [607,'model_name','放大模型'], [612,'chunks','二采 FFN 分块'],
      [613,'noise_seed','二采种子'], [615,'sampler_name','二采采样器'], [616,'sigmas','二采 Sigma']
    ]);
    convert('face', [173,618], '06 视频解码与小脸修复', [
      [618,'enabled','开启修脸'], [618,'face_count','人物数量'],
      [618,'sigmas','修脸 Sigma'], [618,'reverse','反向修脸']
    ]);
    convert('output', [161,562,634,635,636,172], '07 裁去上下文与成片调色', [
      [635,'strength','接续调色强度']
    ]);
    mods.models = find(313); mods.lora = find(314); mods.main = find(320);
    mods.main.title = '04 首采 · 4 步 Euler';
    const labels = {
      context:{video:'上一段 VIDEO'},
      assets:{image:'人物参考图',image_1:'场景参考图',video:'源视频画面',audio_input:'源视频音频'},
      size:{'values.a':'最终宽度','values.a_1':'最终高度'},
      conditions:{plan:'提示词计划',clip:'文本编码器',vae:'视频 VAE',audio_vae:'音频 VAE',
        'ref_images.ref_image_0':'人物参考图','ref_images.ref_image_1':'场景参考图',
        'ref_videos.ref_video_0':'源视频画面','ref_audios.ref_audio_0':'源视频音频',
        image:'上段 22 帧',audio:'上段音频',width:'首采宽度',height:'首采高度',length:'本段总帧数',
        width_1:'最终宽度',height_1:'最终高度',cond:'是否首段'},
      second:{av_latent:'首采 AV Latent','mode.width':'最终宽度','mode.height':'最终高度',model:'主模型',conditioning:'二采条件'},
      face:{samples:'二采 AV Latent',vae:'视频 VAE',model:'精修模型',clip:'文本编码器',
        'references.参考图 1':'人物参考图',enabled:'开启修脸'},
      output:{samples:'二采 AV Latent',vae:'音频 VAE',images:'修复后画面',image_ref:'上段末帧','values.a':'是否首段'},
      lora:{strength_model:'加速 LoRA 强度',strength_swap:'人物替换 LoRA 强度'}
    };
    for (const [key,names] of Object.entries(labels)) {
      const n=mods[key];
      Object.entries(names).forEach(([name,label])=>{
        n.inputs.find(p=>p.name===name).label=label;
        n.subgraph.inputs.find(p=>p.name===name).label=label;
      });
    }
    const outputNames={context:['尾部音频','上段末帧','上下文 22 帧'],
      assets:['素材登记'],size:['首采宽度','首采高度'],conditions:['首采 AV Latent','二采条件','首采条件'],
      second:['二采 AV Latent','精修模型'],face:['修复后画面'],output:['本段 VIDEO']};
    for (const [key,names] of Object.entries(outputNames)) names.forEach((label,i)=>{
      mods[key].outputs[i].label=label;
      mods[key].subgraph.outputs[i].label=label;
    });
    // Main canvas mirrors PGS: loop strip, generation strip, then media and prompt.
    const positions = {
      models:[50,460], lora:[410,460], conditions:[770,460], main:[1130,460],
      second:[1490,460], face:[1850,460], output:[2210,460],
      context:[770,100], assets:[770,1610], size:[1130,1610]
    };
    for (const [key,n] of Object.entries(mods)) {
      n.pos = positions[key];
      n.size = [330, Math.max(150, n.computeSize()[1])];
      n.color = ['context','output'].includes(key) ? '#432' : '#322';
      n.bgcolor = ['context','output'].includes(key) ? '#653' : '#533';
    }
    const place = (id, title, pos, size) => {
      const n=find(id); n.title=title; n.pos=pos; n.size=size; return n;
    };
    place(527,'循环开始 · 连续生成段数',[50,100],[330,240]);
    place(528,'循环结束 · 传递本段 VIDEO',[2570,100],[330,200]);
    place(202,'08 保存本段视频',[2570,460],[330,440]);
    place(518,'人物参考 · Picture 1',[50,1060],[330,470]);
    place(495,'场景参考 · Picture 2',[410,1060],[330,470]);
    place(588,'动作与音频参考 · Video 1',[770,1060],[330,470]);
    place(601,'最终分辨率 · 首采自动取半',[1130,1060],[330,470]);
    place(524,'本段提示词 · 保留素材标签',[1490,1060],[1050,866]);
    const note=place(619,'使用说明',[2570,1060],[330,420]);
    note.widgets[0].value = '# 全模态上下文 · 传统双采\n\n'+
      '**从左向右**：加载 → LoRA → 编码 → 首采 → 传统二采 → 小脸修复 → 裁切调色 → 保存。\n\n'+
      '**双击子流**可展开原节点并替换模块。二采的模型、种子、采样器和 Sigma，以及修脸开关、人数和 Sigma，可直接在主画布修改。\n\n'+
      '**上方循环**控制生成段数。首段自动跳过上下文，后续传递上一段最终 VIDEO 的尾部 22 帧；输出自动裁掉重叠部分。\n\n'+
      '**下方素材**：两张参考图、源视频、最终分辨率与提示词。首采宽高为最终的一半。';
    const workflow=g.serialize();
    for (const s of workflow.definitions.subgraphs) {
      for (const n of s.nodes) {
        const names=targetSockets[n.properties.h3_layout_key];
        if (!names) continue;
        const incident=s.links.filter(l=>l.target_id===n.id && names[l.id]);
        const linkIds=new Set(incident.map(l=>l.id));
        for (const input of n.inputs) if (linkIds.has(input.link)) input.link=null;
        for (const link of incident) {
          const slot=n.inputs.findIndex(i=>i.name===names[link.id]);
          if (slot<0) throw new Error(`Lost input ${n.id}.${names[link.id]}`);
          link.target_slot=slot;
          n.inputs[slot].link=link.id;
        }
      }
    }
    workflow.groups = [
      {id:1,title:'上下文循环 · 上一段最终 VIDEO → 下一段',bounding:[10,20,2930,350],color:'#3f789e',font_size:24,flags:{}},
      {id:2,title:'生成区域 · 从左向右',bounding:[10,390,2930,570],color:'#3f789e',font_size:24,flags:{}},
      {id:3,title:'参考素材与视频分段',bounding:[10,990,1100,1000],color:'#8A8',font_size:24,flags:{}},
      {id:4,title:'最终分辨率',bounding:[1120,990,350,1000],color:'#8A8',font_size:24,flags:{}},
      {id:5,title:'提示词',bounding:[1480,990,1070,1000],color:'#8A8',font_size:24,flags:{}},
      {id:6,title:'使用说明',bounding:[2560,990,380,520],color:'#3f789e',font_size:24,flags:{}}
    ];
    // Lay out every module internally, including the pre-existing model/LoRA modules.
    for (const s of workflow.definitions.subgraphs) {
      s.groups=[];
      const notes=s.nodes.filter(n=>n.type==='MarkdownNote');
      const nodes=s.nodes.filter(n=>n.type!=='MarkdownNote');
      let y=150;
      for (let start=0;start<nodes.length;start+=3) {
        const row=nodes.slice(start,start+3);
        row.forEach((n,i)=>{n.pos=[400+i*560,y]; n.size=[440,Math.max(130,Math.min(n.size[1],650))];});
        y+=Math.max(...row.map(n=>n.size[1]))+140;
      }
      notes.forEach((n,i)=>{n.pos=[400+i*600,y];n.size=[520,300];});
      const right=Math.max(...s.nodes.map(n=>n.pos[0]+n.size[0]))+150;
      s.inputNode.bounding=[30,150,270,Math.max(150,s.inputs.length*24+50)];
      s.outputNode.bounding=[right,150,270,Math.max(150,s.outputs.length*24+50)];
      s.inputs.forEach((port,i)=>{port.pos=[276,174+i*24];});
      s.outputs.forEach((port,i)=>{port.pos=[right+24,174+i*24];});
    }
    workflow.extra.ds={scale:.6,offset:[140,220]};
    workflow.extra.h3_layout='pgs-modular';
    // Native reload checks promoted widgets and nested links in the exact saved JSON.
    await app.loadGraphData(workflow);
    const after = await normalizedPrompt();
    const mismatches=[];
    for (const key of new Set([...Object.keys(before),...Object.keys(after)])) {
      if (JSON.stringify(before[key])!==JSON.stringify(after[key])) mismatches.push({key,before:before[key],after:after[key]});
    }
    window.h3LayoutResult={workflow,before,after,mismatches};
    if (mismatches.length) throw new Error(JSON.stringify(mismatches));
    app.canvas.ds.scale=.6; app.canvas.ds.offset=[140,220]; app.canvas.setDirty(true,true);
    return {root:workflow.nodes.length,subgraphs:workflow.definitions.subgraphs.length,
      executableNodes:Object.keys(after).length,mismatches,
      modules:app.graph._nodes.filter(n=>n.isSubgraphNode()).map(n=>({id:n.id,title:n.title,
        size:Array.from(n.size),widgets:n.widgets?.map(w=>({name:w.name,value:w.value}))}))};
  }, __H3_CONTEXT_WORKFLOW__);
}
