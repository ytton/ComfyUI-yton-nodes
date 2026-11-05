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
    for(const pattern of ["**/yton/replacement/**","**/view?**","**/upload/image"])
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
      const node=LiteGraph.createNode("YtonReplacementPlan");
      app.graph.add(node);node.pos=[30,80];app.canvas.ds.scale=1;app.canvas.ds.offset=[0,0];
      node.widgets.find(widget=>widget.name==="config").value=JSON.stringify(config);
      node.onConfigure();window.replacementSelectionNode=node;
    },{definitions,config});
    await page.getByRole("button",{name:"关键帧替换",exact:true}).click();
    const dialog=page.locator(".yr-anchor-dialog");
    const slider=dialog.getByRole("slider",{name:"当前帧",exact:true});
    await page.waitForFunction(()=>document.querySelector('.yr-anchor-slider')?.disabled===false);
    await dialog.locator("video").evaluate(video=>video.readyState>=2 || new Promise(resolve=>video.addEventListener('loadeddata',resolve,{once:true})));
    check(await dialog.locator('.yr-anchor-counter').textContent()==="1 / 39 帧","frame-only counter");
    await page.keyboard.press('c');
    await dialog.locator('.yr-anchor-row').first().locator('img').waitFor();
    check(await dialog.locator('.yr-anchor-row').count()===1,"C collects exactly one frame");
    await page.keyboard.press('c');
    check(await dialog.locator('.yr-anchor-row').count()===1,"same frame is not collected twice");
    const imageURL=new URL(await dialog.locator('.yr-anchor-row img').first().getAttribute('src'),page.url());
    const png=await(await page.request.get('http://127.0.0.1:8190'+imageURL.pathname.replace(/^\/api/,'')+imageURL.search)).body();
    await dialog.locator('input[type=file]').first().setInputFiles({name:'edited.png',mimeType:'image/png',buffer:png});
    await dialog.locator('.yr-anchor-image img').nth(1).waitFor();
    await page.waitForFunction(()=>document.querySelectorAll('.yr-anchor-row .yr-anchor-image img')[1]?.naturalWidth>0);
    check(await dialog.locator('.yr-anchor-list-heading').textContent()==="替换帧1 / 1 已上传","uploaded count");
    const box=await slider.boundingBox();
    await page.mouse.move(box.x+4,box.y+box.height/2);
    await page.mouse.down();
    await page.mouse.move(box.x+box.width*.65,box.y+box.height/2,{steps:12});
    await page.mouse.up();
    await page.waitForFunction(()=>document.querySelector('.yr-anchor-stage video')?.seeking===false);
    check(Math.abs(Number(await slider.inputValue())-25)<=1,"pointer drag follows frames");
    await slider.evaluate(input=>{input.value="20";input.dispatchEvent(new Event('input',{bubbles:true}));});
    await page.waitForFunction(()=>document.querySelector('.yr-anchor-stage video')?.seeking===false);
    await page.keyboard.press('c');
    await dialog.locator('.yr-anchor-row[data-frame="20"] img').waitFor();
    check(await dialog.locator('.yr-anchor-counter').textContent()==="21 / 39 帧","drag seeks correct frame");
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(()=>document.querySelector('.yr-anchor-stage video')?.seeking===false);
    check(await dialog.locator('.yr-anchor-counter').textContent()==="22 / 39 帧","single-frame stepping");
    await page.keyboard.press('Space');
    await page.waitForFunction(()=>!document.querySelector('.yr-anchor-stage video').paused);
    await page.keyboard.press('Space');
    await page.waitForFunction(()=>document.querySelector('.yr-anchor-stage video').paused);
    const saved=await page.evaluate(()=>JSON.parse(window.replacementSelectionNode.widgets.find(w=>w.name==='config').value).anchors);
    check(Object.values(saved)[0].map(x=>x.frame).join(',')==='0,20',"selection persisted in node configuration");
    check(Boolean(Object.values(saved)[0][0].image),"uploaded image path persisted");
    await dialog.getByRole('button',{name:'完成',exact:true}).click();
    await dialog.waitFor({state:'detached'});
    await page.getByRole('button',{name:'关键帧替换',exact:true}).click();
    await dialog.locator('.yr-anchor-row').nth(1).waitFor();
    check(await dialog.locator('.yr-anchor-list-heading').textContent()==="替换帧1 / 2 已上传","reopen preserves pairs");
    await page.setViewportSize({width:680,height:720});
    const geometry=await dialog.evaluate(element=>({width:element.clientWidth,scroll:element.scrollWidth,height:element.clientHeight,scrollHeight:element.scrollHeight}));
    check(geometry.scroll===geometry.width && geometry.scrollHeight===geometry.height,"dialog fits small viewport without outer overflow");
    await page.keyboard.press('Escape');
    await dialog.waitFor({state:'detached'});
    await page.setViewportSize({width:1660,height:1050});
    const selection=page.getByLabel('查看片段提示词',{exact:true});
    await selection.selectOption('1');
    await page.getByRole('button',{name:'关键帧替换',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.yr-anchor-slider')?.disabled===false);
    check(await dialog.locator('.yr-anchor-row').count()===0,"next segment has independent markers");
    await page.keyboard.press('c');
    await dialog.locator('.yr-anchor-row img').waitFor();
    await dialog.getByRole('button',{name:'移除第 1 帧',exact:true}).click();
    check(await dialog.locator('.yr-anchor-row').count()===0,"remove marker");
    await dialog.getByRole('button',{name:'完成',exact:true}).click();
    await selection.selectOption('0');
    await page.getByRole('button',{name:'关键帧替换',exact:true}).click();
    await dialog.locator('.yr-anchor-row').nth(1).waitFor();
    check(await dialog.locator('.yr-anchor-list-heading').textContent()==="替换帧1 / 2 已上传","first segment retained after navigation");
    await page.evaluate(()=>window.comfyAPI.app.app.graph.remove(window.replacementSelectionNode));
    await dialog.waitFor({state:'detached'});
    const workflow=await(await page.request.get('http://127.0.0.1:8190/anchor-workflow')).json();
    await page.evaluate(async workflow=>{ await window.comfyAPI.app.app.loadGraphData(workflow); },workflow);
    const wired=await page.evaluate(async()=>{
      const app=window.comfyAPI.app.app;
      const omni=app.graph._nodes.find(n=>n.type==='YtonH3TraditionalOmniGenerate');
      const planner=app.graph._nodes.find(n=>n.type==='YtonReplacementPlan');
      const {output}=await app.graphToPrompt();
      return {enabled:omni.widgets.find(w=>w.name==='enable_add_guide').value,
        anchors:output[String(omni.id)].inputs.anchor_images,planner:String(planner.id),
        outputName:planner.outputs[1].name,
        prompt:output[String(omni.id)].inputs.prompt};
    });
    check(wired.enabled===true,'saved workflow enables Add Guide');
    check(wired.outputName==='achorImages' && wired.anchors[0]===wired.planner && wired.anchors[1]===1,'saved workflow connects keyframe payload');
    check(wired.prompt[1]===2,'existing prompt link remains correct');
    return {checks:['processed video and frame counter','C capture and deduplication','image upload','timeline seek','frame stepping','play/pause','config persistence','reopen','small viewport','per-segment isolation','delete','node removal cleanup','full workflow serialization and Add Guide link']};
  } finally { await context.close(); }
}
