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
    const optimized={shared:{text:"保留共用优化提示词",signature:"shared-fixture"},
      "0":{text:"保留第一段优化提示词",signature:"first-fixture"},
      "1":{text:"保留第二段优化提示词",signature:"second-fixture"}};
    config.optimized=optimized;
    config.compression.max_edge=0;
    config.compression.width=160;
    config.compression.height=96;
    for(const definition of Object.values(definitions)) definition.python_module="custom_nodes.ComfyUI-yton-nodes";
    await page.evaluate(async({definition,config})=>{
      const app=window.comfyAPI.app.app;
      await app.loadGraphData({version:0.4,nodes:[],links:[],groups:[],config:{},extra:{}});
      await app.registerNodesFromDefs(definition);
      const node=LiteGraph.createNode("YtonReplacementPlan");
      app.graph.add(node);
      node.pos=[30,80];app.canvas.ds.scale=1;app.canvas.ds.offset=[0,0];
      node.widgets.find(widget=>widget.name==="config").value=JSON.stringify(config);
      node.onConfigure();
      window.replacementCompressionNode=node;
    },{definition:definitions,config});
    await page.locator(".yr-pgs-rich-editor").waitFor();
    await page.getByLabel("查看片段提示词",{exact:true}).locator("option").filter({hasText:"第 1 / 2 段"}).waitFor({state:"attached"});
    await page.getByRole("button",{name:"本段优化",exact:true}).click();
    check((await page.locator(".yr-pgs-rich-editor").innerText()).includes(optimized["0"].text),"existing optimized prompt is shown");
    await page.getByRole("button",{name:"编辑",exact:true}).click();
    const dialog=page.locator(".yr-pgs-ov");
    await dialog.locator(".yr-pgs-seg-item").first().waitFor();
    await dialog.getByTitle("等比锁定",{exact:true}).click();
    await dialog.getByLabel("参考视频压缩宽度",{exact:true}).fill("80");
    await dialog.getByLabel("参考视频压缩高度",{exact:true}).fill("48");
    await dialog.getByRole("button",{name:"保存",exact:true}).click();
    await dialog.waitFor({state:"detached"});
    const result=await page.evaluate(()=>JSON.parse(window.replacementCompressionNode.widgets.find(widget=>widget.name==="config").value));
    check(result.compression.width===80 && result.compression.height===48,"new reference compression is applied");
    check(JSON.stringify(result.optimized)===JSON.stringify(optimized),"all optimized prompts are retained");
    check((await page.locator(".yr-pgs-rich-editor").innerText()).includes(optimized["0"].text),"optimized editor remains populated");
    await page.getByLabel("全段共用提示词",{exact:true}).check();
    check((await page.locator(".yr-pgs-rich-editor").innerText()).includes(optimized.shared.text),"shared optimized prompt remains available");
    await page.getByRole("button",{name:"编辑",exact:true}).click();
    await dialog.locator(".yr-pgs-seg-item").first().waitFor();
    await dialog.getByRole("button",{name:"保存",exact:true}).click();
    await dialog.waitFor({state:"detached"});
    check((await page.locator(".yr-pgs-rich-editor").innerText()).includes(optimized.shared.text),"saving unchanged editor retains shared prompt");
    return {checks:["compression-only save", "per-segment optimized prompts retained", "shared optimized prompt retained", "unchanged save"],compression:[80,48]};
  } catch(error) {
    const state=await page.evaluate(()=>{const app=window.comfyAPI?.app?.app;return {
      ready:app?.vueAppReady,sequence:app?.graphLoadSequence,committed:app?.committedGraphLoadSequence,
      pending:app?.pendingGraphLoads?.size,type:!!window.LiteGraph?.registered_node_types?.YtonReplacementPlan,
      panels:document.querySelectorAll('.yton-replacement-panel').length,status:[...document.querySelectorAll('.yr-status')].map(node=>node.textContent),
      nodes:app?.rootGraph?._nodes.map(node=>({type:node.type,widgets:node.widgets?.map(widget=>({name:widget.name,element:!!widget.element}))})),
      testNode:window.replacementCompressionNode?.id};});
    throw new Error(error.message+'\n'+JSON.stringify(state));
  } finally {await context.close();}
}
