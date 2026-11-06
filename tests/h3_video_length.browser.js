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
    check(Object.keys(definition.input.required).join(',')==='video,original_frames','只有视频和原长度两个输入');
    const result=await page.evaluate(async definitions=>{
      const app=window.comfyAPI.app.app;
      await app.loadGraphData({version:.4,nodes:[],links:[],groups:[],config:{},extra:{}});
      await app.registerNodesFromDefs(definitions);
      const pad=LiteGraph.createNode('YtonH3VideoLength'),restore=LiteGraph.createNode('YtonH3VideoLength'),parser=LiteGraph.createNode('YtonViggleReplacementSegment');
      for(const node of [pad,restore,parser])app.graph.add(node);
      pad.pos=[80,140];restore.pos=[460,140];parser.pos=[840,140];
      app.canvas.ds.scale=.9;app.canvas.ds.offset=[0,0];
      const original=restore.widgets.find(w=>w.name==='original_frames');
      const defaults={pad:pad.widgets.find(w=>w.name==='original_frames').value,restore:original.value};
      restore.convertWidgetToInput(original);
      pad.connect(4,restore,restore.inputs.findIndex(i=>i.name==='original_frames'));
      const workflow=app.graph.serialize();
      const {output}=await app.graphToPrompt();
      window.lengthTest={pad,restore,parser,workflow};
      return {defaults,pad:{widgets:pad.widgets.map(w=>w.name),outputs:pad.outputs.map(o=>o.name),size:pad.size},restore:output[String(restore.id)],
        parser:parser.outputs.map(o=>({name:o.name,type:o.type})),padId:pad.id,workflow};
    },definitions);
    check(result.defaults.pad===0 && result.defaults.restore===0,'原长度默认 0，自动补帧');
    check(result.pad.widgets.length===1 && result.pad.widgets[0]==='original_frames','界面只显示一个原长度控件');
    check(result.pad.outputs.length===5 && result.pad.size[1]<300,'输出普通媒体和整数，节点保持紧凑');
    check(result.restore.inputs.original_frames[0]===String(result.padId) && result.restore.inputs.original_frames[1]===4,'补帧节点原长度可直接连接恢复节点');
    check(result.parser.at(-2).name==='上下文长度（帧）' && result.parser.at(-2).type==='INT','解析器提供上下文帧数输出');
    check(result.parser.at(-1).name==='是否首段' && result.parser.at(-1).type==='BOOLEAN','解析器提供是否首段输出');
    const restored=await page.evaluate(async()=>{
      const app=window.comfyAPI.app.app;
      await app.loadGraphData(window.lengthTest.workflow);
      const {output}=await app.graphToPrompt();
      return Object.values(output).filter(node=>node.class_type==='YtonH3VideoLength').map(node=>node.inputs.original_frames);
    });
    check(restored.some(value=>value===0) && restored.some(Array.isArray),'工作流保存重载后保留原长度连线');
    await page.screenshot({path:'F:/ComfyUI/ComfyUI/custom_nodes/ComfyUI-yton-nodes/.artifacts/h3-video-length.png',fullPage:true});
    check(!errors.length,'浏览器无运行错误：'+errors.join(';'));
    return {checks,errors};
  } finally {await context.close();}
}
