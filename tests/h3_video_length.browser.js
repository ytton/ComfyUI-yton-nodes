// Start tests/viggle_preview_server.py; validate schemas and ordinary workflow links.
async (basePage) => {
  const context=await basePage.context().browser().newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage(),checks=[],errors=[];
  const check=(value,text)=>{if(!value)throw new Error(text);checks.push(text);};
  page.on('pageerror',error=>errors.push(error.message));
  try {
    for(const pattern of ["**/userdata/**","**/settings/**"])
      await page.route(pattern,route=>["POST","PUT","DELETE"].includes(route.request().method())?route.fulfill({json:{}}):route.continue());
    await page.route(/\/(?:api\/)?settings$/,async route=>{
      if(route.request().method()!=="GET")return route.fulfill({json:{}});
      const response=await route.fetch();return route.fulfill({json:{...await response.json(),"Comfy.Workflow.Persist":false,"Comfy.Workflow.AutoSave":"off","Comfy.VueNodes.Enabled":false}});
    });
    await page.route("**/prompt",route=>route.request().method()==="POST"?route.abort():route.continue());
    await page.goto('http://127.0.0.1:8188/');
    await page.waitForFunction(()=>{
      const app=window.comfyAPI?.app?.app;
      return app?.vueAppReady && app.graphLoadSequence && app.committedGraphLoadSequence===app.graphLoadSequence && !app.pendingGraphLoads.size && window.LiteGraph?.registered_node_types?.YtonReplacementPlan;
    },{},{timeout:60000});
    const definitions=await(await page.request.get('http://127.0.0.1:8191/definitions')).json();
    for(const definition of Object.values(definitions))definition.python_module='custom_nodes.ComfyUI-yton-nodes';
    check(!definitions.YtonViggleVideoLength,'长度调整器已独立出 Viggle 节点列表');
    const definition=definitions.YtonH3VideoLength;
    check(definition.display_name==='H3 视频长度调整' && definition.category==='yton-nodes/MiniMax H3','通用节点名称和分类正确');
    check(Object.keys(definition.input.required).join(',')==='video,mode,original_frames,context_frames,first_segment','明确提供处理模式、原长度、上下文和首段参数');
    const result=await page.evaluate(async definitions=>{
      const app=window.comfyAPI.app.app;
      await app.loadGraphData({version:.4,nodes:[],links:[],groups:[],config:{},extra:{}});
      await app.registerNodesFromDefs(definitions);
      const pad=LiteGraph.createNode('YtonH3VideoLength'),restore=LiteGraph.createNode('YtonH3VideoLength'),parser=LiteGraph.createNode('YtonViggleReplacementSegment');
      for(const node of [pad,restore,parser])app.graph.add(node);
      parser.pos=[50,140];pad.pos=[500,140];restore.pos=[940,140];
      app.canvas.ds.scale=.9;app.canvas.ds.offset=[0,0];
      const defaults={pad:pad.widgets.find(w=>w.name==='mode').value};
      restore.widgets.find(w=>w.name==='mode').value='复原';
      for(const name of ['original_frames','context_frames','first_segment'])restore.convertWidgetToInput(restore.widgets.find(w=>w.name===name));
      parser.connect(0,pad,0);
      pad.connect(0,restore,0);
      parser.connect(14,restore,restore.inputs.findIndex(i=>i.name==='original_frames'));
      parser.connect(12,restore,restore.inputs.findIndex(i=>i.name==='context_frames'));
      parser.connect(13,restore,restore.inputs.findIndex(i=>i.name==='first_segment'));
      const workflow=app.graph.serialize();
      const {output}=await app.graphToPrompt();
      window.lengthTest={pad,restore,parser,workflow};
      return {defaults,pad:{widgets:pad.widgets.map(w=>w.name),outputs:pad.outputs.map(o=>o.name),size:pad.size},restore:output[String(restore.id)],
        parser:parser.outputs.map(o=>({name:o.name,type:o.type})),parserId:parser.id,workflow};
    },definitions);
    check(result.defaults.pad==='延长' && result.restore.inputs.mode==='复原','两个节点明确区分延长与复原模式');
    check(result.pad.widgets.join(',')==='mode,original_frames,context_frames,first_segment','界面显示模式和三个直接可配置参数');
    check(result.pad.outputs.join(',')==='视频,视频帧,音频' && result.pad.size[1]<300,'长度调整节点只输出视频、视频帧和音频，节点保持紧凑');
    check(result.restore.inputs.original_frames[0]===String(result.parserId) && result.restore.inputs.original_frames[1]===14,'解析器原始片段长度可直接连接复原节点');
    check(result.parser[12].name==='上下文长度' && result.parser[12].type==='INT','解析器的上下文长度显示名称正确');
    check(result.parser[13].name==='是否首段' && result.parser[13].type==='BOOLEAN','解析器提供是否首段输出');
    check(result.parser[14].name==='原始片段长度（帧）' && result.parser[14].type==='INT','解析器提供原始片段的帧数');
    check(result.restore.inputs.context_frames[1]===12 && result.restore.inputs.first_segment[1]===13,'解析器的上下文和首段布尔值可直接连接到复原节点');
    const restored=await page.evaluate(async()=>{
      const app=window.comfyAPI.app.app;
      await app.loadGraphData(window.lengthTest.workflow);
      const {output}=await app.graphToPrompt();
      return Object.values(output).filter(node=>node.class_type==='YtonH3VideoLength').map(node=>node.inputs);
    });
    check(restored.some(value=>value.mode==='延长') && restored.some(value=>value.mode==='复原' && Array.isArray(value.original_frames) && Array.isArray(value.context_frames) && Array.isArray(value.first_segment)),'工作流重载保留处理模式及全部复原连线');
    await page.screenshot({path:'F:/ComfyUI/ComfyUI/custom_nodes/ComfyUI-yton-nodes/.artifacts/h3-video-length.png',fullPage:true});
    check(!errors.length,'浏览器无运行错误：'+errors.join(';'));
    return {checks,errors};
  } finally {await context.close();}
}
