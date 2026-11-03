// CPU fixture: start tests/replacement_preview_server.py before this regression.
async (basePage) => {
  const context=await basePage.context().browser().newContext({viewport:{width:1660,height:1050}});
  const page=await context.newPage();
  const check=(condition,message)=>{if(!condition) throw new Error(message);};
  try {
    for(const pattern of ["**/userdata/**","**/settings/**"])
      await page.route(pattern,route=>["POST","PUT","DELETE"].includes(route.request().method()) ? route.fulfill({json:{}}) : route.continue());
    await page.route(/\/(?:api\/)?settings$/,async route=>{
      if(route.request().method()!=="GET") return route.fulfill({json:{}});
      const response=await route.fetch();
      return route.fulfill({json:{...await response.json(),"Comfy.Workflow.Persist":false,"Comfy.Workflow.AutoSave":"off","Comfy.VueNodes.Enabled":false}});
    });
    await page.route("**/prompt",route=>route.request().method()==="POST" ? route.abort() : route.continue());
    for(const pattern of ["**/yton/replacement/**","**/view?**"])
      await page.route(pattern,async route=>{
        const url=new URL(route.request().url());
        await route.fulfill({response:await route.fetch({url:"http://127.0.0.1:8190"+url.pathname.replace(/^\/api/,"")+url.search})});
      });
    await page.goto("http://127.0.0.1:8188/");
    await page.waitForFunction(()=>{
      const app=window.comfyAPI?.app?.app;
      if(!app?.vueAppReady || !app.graphLoadSequence || app.committedGraphLoadSequence!==app.graphLoadSequence
          || app.pendingGraphLoads.size || !window.LiteGraph?.registered_node_types?.YtonReplacementPlan) return false;
      if(window.replacementReadySequence!==app.graphLoadSequence) {
        window.replacementReadySequence=app.graphLoadSequence;window.replacementReadyTime=performance.now();
      }
      return performance.now()-window.replacementReadyTime>1000;
    },{},{timeout:60000});
    const definitions=await(await page.request.get("http://127.0.0.1:8190/definitions")).json();
    const config=await(await page.request.get("http://127.0.0.1:8190/config")).json();
    for(const definition of Object.values(definitions)) definition.python_module="custom_nodes.ComfyUI-yton-nodes";
    await page.evaluate(async({definitions,config})=>{
      const app=window.comfyAPI.app.app;
      await app.loadGraphData({version:0.4,nodes:[],links:[],groups:[],config:{},extra:{}});
      await app.registerNodesFromDefs(definitions);
      const node=LiteGraph.createNode("YtonCharacterReplacement");
      app.graph.add(node);node.pos=[30,80];app.canvas.ds.scale=1;app.canvas.ds.offset=[0,0];
      node.widgets.find(widget=>widget.name==="config").value=JSON.stringify(config);
      node.onConfigure();window.replacementSelectionNode=node;
    },{definitions,config});
    const selection=page.getByLabel("查看片段提示词",{exact:true});
    await selection.locator("option").filter({hasText:"第 1 / 2 段"}).waitFor({state:"attached"});
    await selection.selectOption("1");
    const selected=await page.evaluate(async()=>{
      const node=window.replacementSelectionNode;
      const {output}=await window.comfyAPI.app.app.graphToPrompt();
      return {inputs:output[String(node.id)].inputs,hidden:node.widgets.find(widget=>widget.name==="selected_index").hidden};
    });
    check(selected.inputs.selected_index===1,"the selected segment is sent to execution");
    check(!Object.hasOwn(selected.inputs,"index"),"unconnected index is omitted");
    check(selected.hidden,"selection does not add an editable numeric widget");
    await page.getByRole("button",{name:"上一段",exact:true}).click();
    check(await page.evaluate(()=>window.replacementSelectionNode.widgets.find(widget=>widget.name==="selected_index").value)===0,"previous button updates execution selection");
    await page.getByRole("button",{name:"下一段",exact:true}).click();
    await page.getByLabel("全段共用提示词",{exact:true}).check();
    check(await selection.inputValue()==="1","shared prompt mode retains the selected video segment");
    await page.evaluate(()=>{
      const node=window.replacementSelectionNode;
      const saved=node.serialize();
      node.widgets.find(widget=>widget.name==="selected_index").value=0;
      node.configure(saved);
    });
    await page.waitForFunction(()=>document.querySelector('.yr-current')?.value==="1");
    const connected=await page.evaluate(async()=>{
      const app=window.comfyAPI.app.app,node=window.replacementSelectionNode;
      const integer=LiteGraph.createNode("PrimitiveInt");app.graph.add(integer);
      integer.widgets.find(widget=>widget.name==="value").value=0;
      integer.connect(0,node,node.inputs.findIndex(input=>input.name==="index"));
      const {output}=await app.graphToPrompt();
      return {inputs:output[String(node.id)].inputs,source:String(integer.id)};
    });
    check(connected.inputs.selected_index===1,"panel selection remains available with an external index");
    check(Array.isArray(connected.inputs.index) && connected.inputs.index[0]===connected.source,"external index connection is submitted");
    await page.evaluate(({config})=>{
      const app=window.comfyAPI.app.app;app.graph.clear();
      const planner=LiteGraph.createNode("YtonReplacementPlan"),parser=LiteGraph.createNode("YtonReplacementSegment");
      app.graph.add(planner);app.graph.add(parser);planner.pos=[30,80];parser.pos=[900,80];
      planner.widgets.find(widget=>widget.name==="config").value=JSON.stringify(config);planner.onConfigure();
      planner.connect(0,parser,parser.inputs.findIndex(input=>input.name==="plan"));
      window.replacementSelectionNode=planner;window.replacementParserNode=parser;
    },{config});
    await selection.locator("option").filter({hasText:"第 1 / 2 段"}).waitFor({state:"attached"});
    await selection.selectOption("1");
    const parsed=await page.evaluate(async()=>{
      const {output}=await window.comfyAPI.app.app.graphToPrompt();
      return {plan:output[String(window.replacementSelectionNode.id)].inputs,parser:output[String(window.replacementParserNode.id)].inputs};
    });
    check(parsed.plan.selected_index===1 && !Object.hasOwn(parsed.parser,"index"),"config output carries the selection to an unconnected parser");
    return {checks:["selected segment submitted", "arrow navigation", "shared prompt mode", "workflow serialization", "external index connection", "config parser selection"]};
  } finally {await context.close();}
}
