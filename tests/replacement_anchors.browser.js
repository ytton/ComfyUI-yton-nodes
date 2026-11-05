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
      node.addOutput("achorImages","YTON_H3_ANCHOR_IMAGES");
      node.onConfigure();window.replacementSelectionNode=node;
    },{definitions,config});
    check(await page.evaluate(()=>window.replacementSelectionNode.outputs.length)===1,'configurator keeps only current segment configuration output');
    await page.getByRole("button",{name:"关键帧替换",exact:true}).click();
    const dialog=page.locator(".yr-anchor-dialog");
    const slider=dialog.getByRole("slider",{name:"当前帧",exact:true});
    await page.waitForFunction(()=>document.querySelector('.yr-anchor-slider')?.disabled===false);
    await dialog.locator("video").evaluate(video=>video.readyState>=2 || new Promise(resolve=>video.addEventListener('loadeddata',resolve,{once:true})));
    check(await dialog.locator('.yr-anchor-counter').textContent()==="1 / 39 帧","frame-only counter");
    await page.keyboard.press('c');
    await dialog.locator('.yr-anchor-card').first().locator('img').waitFor();
    check(await dialog.locator('.yr-anchor-card').count()===1,"C collects exactly one frame");
    await page.keyboard.press('c');
    check(await dialog.locator('.yr-anchor-card').count()===1,"same frame is not collected twice");
    const imageBytes=await dialog.locator('.yr-anchor-card img').first().evaluate(async image=>Array.from(new Uint8Array(await(await fetch(image.src)).arrayBuffer())));
    const png=await(await page.request.get('http://127.0.0.1:8190/view?filename=red.png&type=input')).body();
    await dialog.locator('input[type=file]').first().setInputFiles({name:'edited.png',mimeType:'image/png',buffer:png});
    await dialog.locator('.yr-anchor-image img').nth(1).waitFor();
    await page.waitForFunction(()=>document.querySelectorAll('.yr-anchor-card .yr-anchor-image img')[1]?.naturalWidth>0);
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
    await dialog.locator('.yr-anchor-card[data-frame="20"] img').waitFor();
    check(await dialog.locator('.yr-anchor-counter').textContent()==="21 / 39 帧","drag seeks correct frame");
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(()=>document.querySelector('.yr-anchor-stage video')?.seeking===false);
    check(await dialog.locator('.yr-anchor-counter').textContent()==="22 / 39 帧","single-frame stepping");
    await page.keyboard.press('Space');
    await page.waitForFunction(()=>!document.querySelector('.yr-anchor-stage video').paused);
    await page.keyboard.press('Space');
    await page.waitForFunction(()=>document.querySelector('.yr-anchor-stage video').paused);
    const layout=await dialog.locator('.yr-anchor-card').evaluateAll(cards=>cards.map(card=>{const box=card.getBoundingClientRect();return {x:box.x,y:box.y,width:box.width};}));
    check(layout.length===2 && Math.abs(layout[0].y-layout[1].y)<2 && layout[1].x>layout[0].x,'cards arranged in two columns');
    check(await dialog.locator('.yr-anchor-pin span').allTextContents().then(labels=>labels.join(','))==='1,2','numbered timeline markers match cards');
    const download=dialog.getByRole('link',{name:'下载第 1 帧',exact:true});
    check(await download.getAttribute('download')==='source_第1帧.png','download includes source video name and frame');
    const downloadFrame=async(link,name,expected)=>{
      check((await link.getAttribute('href')).startsWith('blob:'),'frame downloads use a local file URL');
      const [downloaded]=await Promise.all([page.waitForEvent('download'),link.click()]);
      check(downloaded.suggestedFilename()===name,'browser download filename');
      check(await downloaded.failure()===null,'frame download completes');
      const bytes=[];
      for await(const chunk of await downloaded.createReadStream()) bytes.push(...chunk);
      check(bytes.length===expected.length && bytes.every((value,index)=>value===expected[index]),'downloaded PNG matches selected original frame');
    };
    await downloadFrame(download,'source_第1帧.png',imageBytes);
    const secondDownload=dialog.getByRole('link',{name:'下载第 21 帧',exact:true});
    const secondBytes=await dialog.locator('.yr-anchor-card[data-frame="20"] .yr-anchor-column:first-child img').evaluate(async image=>Array.from(new Uint8Array(await(await fetch(image.src)).arrayBuffer())));
    await downloadFrame(secondDownload,'source_第21帧.png',secondBytes);
    const marker=dialog.getByRole('slider',{name:'调整关键帧 1',exact:true});
    const markerBox=await marker.boundingBox();
    const trackBox=await dialog.locator('.yr-anchor-track').boundingBox();
    await page.mouse.move(markerBox.x+markerBox.width/2,markerBox.y+8);
    await page.mouse.down();
    await page.mouse.move(markerBox.x+markerBox.width/2+trackBox.width*8/38,markerBox.y+8,{steps:10});
    await page.mouse.up();
    await dialog.locator('.yr-anchor-card[data-marker="0"][data-frame="8"] img').first().waitFor();
    check(await dialog.getByRole('spinbutton',{name:'关键帧 1 的帧号'}).inputValue()==='9','drag updates card frame number');
    check(await dialog.locator('.yr-anchor-counter').textContent()==='9 / 39 帧','drag previews new frame');
    check(await dialog.locator('.yr-anchor-card[data-marker="0"] .stale').textContent()==='帧位置已调整，请上传对应的替换图','moved uploaded edit marked stale');
    check(await dialog.locator('.yr-anchor-list-heading').textContent()==='替换帧0 / 2 已上传','stale edit excluded from ready count');
    await dialog.getByRole('spinbutton',{name:'关键帧 1 的帧号'}).fill('10');
    await dialog.getByRole('spinbutton',{name:'关键帧 1 的帧号'}).press('Tab');
    await dialog.locator('.yr-anchor-card[data-marker="0"][data-frame="9"] img').first().waitFor();
    const adjustedDownload=dialog.getByRole('link',{name:'下载第 10 帧',exact:true});
    check(await adjustedDownload.getAttribute('download')==='source_第10帧.png','download follows adjusted frame');
    const adjustedBytes=await dialog.locator('.yr-anchor-card[data-frame="9"] .yr-anchor-column:first-child img').evaluate(async image=>Array.from(new Uint8Array(await(await fetch(image.src)).arrayBuffer())));
    await downloadFrame(adjustedDownload,'source_第10帧.png',adjustedBytes);
    await dialog.getByRole('slider',{name:'调整关键帧 1',exact:true}).focus();
    await page.keyboard.press('ArrowRight');
    await dialog.locator('.yr-anchor-card[data-marker="0"][data-frame="10"] img').first().waitFor();
    check(await dialog.getByRole('spinbutton',{name:'关键帧 1 的帧号'}).inputValue()==='11','marker keyboard adjustment');
    await dialog.getByRole('slider',{name:'调整关键帧 1',exact:true}).focus();
    await page.keyboard.press('End');
    await dialog.locator('.yr-anchor-card[data-marker="0"][data-frame="38"] img').first().waitFor();
    check(await dialog.getByRole('spinbutton',{name:'关键帧 1 的帧号'}).inputValue()==='39','marker reaches last frame');
    await dialog.getByRole('spinbutton',{name:'关键帧 1 的帧号'}).fill('21');
    await dialog.getByRole('spinbutton',{name:'关键帧 1 的帧号'}).press('Tab');
    check(await dialog.getByRole('spinbutton',{name:'关键帧 1 的帧号'}).inputValue()!=='21','markers cannot overlap');
    await dialog.getByRole('spinbutton',{name:'关键帧 1 的帧号'}).fill('11');
    await dialog.getByRole('spinbutton',{name:'关键帧 1 的帧号'}).press('Tab');
    await dialog.getByRole('button',{name:'选择关键帧 1',exact:true}).click();
    await page.evaluate(base64=>{
      const bytes=Uint8Array.from(atob(base64),char=>char.charCodeAt(0));
      const transfer=new DataTransfer();
      transfer.items.add(new File([bytes],'edited-new.png',{type:'image/png'}));
      document.querySelector('.yr-anchor-dialog').dispatchEvent(new ClipboardEvent('paste',{clipboardData:transfer,bubbles:true,cancelable:true}));
    },png.toString('base64'));
    await page.waitForFunction(()=>document.querySelector('.yr-anchor-list-heading').textContent==='替换帧1 / 2 已上传');
    check(await page.evaluate(()=>JSON.parse(window.replacementSelectionNode.widgets.find(w=>w.name==='config').value).images[0])==='red.png','pasting into modal does not upload into node reference slots');
    await dialog.locator('.yr-anchor-card[data-marker="1"] .yr-anchor-column:nth-child(2) .yr-anchor-image').evaluate((element,base64)=>{
      const bytes=Uint8Array.from(atob(base64),char=>char.charCodeAt(0));
      const transfer=new DataTransfer();
      transfer.items.add(new File([bytes],'dropped.png',{type:'image/png'}));
      element.dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));
    },png.toString('base64'));
    await page.waitForFunction(()=>document.querySelector('.yr-anchor-list-heading').textContent==='替换帧2 / 2 已上传');
    await dialog.getByRole('button',{name:'清空第 21 帧的替换图片',exact:true}).click();
    check(await dialog.locator('.yr-anchor-list-heading').textContent()==='替换帧1 / 2 已上传','clearing replacement keeps source marker');
    const saved=await page.evaluate(()=>JSON.parse(window.replacementSelectionNode.widgets.find(w=>w.name==='config').value).anchors);
    check(Object.values(saved)[0].map(x=>x.frame).join(',')==='10,20',"selection persisted in node configuration");
    check(Boolean(Object.values(saved)[0][0].image) && !Object.values(saved)[0][0].stale,"new upload clears stale state");
    await dialog.getByRole('button',{name:'完成',exact:true}).click();
    await dialog.waitFor({state:'detached'});
    await page.getByRole('button',{name:'关键帧替换',exact:true}).click();
    await dialog.locator('.yr-anchor-card').nth(1).waitFor();
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
    check(await dialog.locator('.yr-anchor-card').count()===0,"next segment has independent markers");
    await page.keyboard.press('c');
    await dialog.locator('.yr-anchor-card img').waitFor();
    await dialog.getByRole('button',{name:'移除第 1 帧',exact:true}).click();
    check(await dialog.locator('.yr-anchor-card').count()===0,"remove marker");
    await dialog.getByRole('button',{name:'完成',exact:true}).click();
    await selection.selectOption('0');
    await page.getByRole('button',{name:'关键帧替换',exact:true}).click();
    await dialog.locator('.yr-anchor-card').nth(1).waitFor();
    check(await dialog.locator('.yr-anchor-list-heading').textContent()==="替换帧1 / 2 已上传","first segment retained after navigation");
    await page.evaluate(()=>window.comfyAPI.app.app.graph.remove(window.replacementSelectionNode));
    await dialog.waitFor({state:'detached'});
    const workflow=await(await page.request.get('http://127.0.0.1:8190/anchor-workflow')).json();
    workflow.nodes.find(node=>node.type==='YtonReplacementPlan').outputs.push({name:'achorImages',type:'YTON_H3_ANCHOR_IMAGES',links:[]});
    await page.evaluate(async workflow=>{ await window.comfyAPI.app.app.loadGraphData(workflow); },workflow);
    const wired=await page.evaluate(async()=>{
      const app=window.comfyAPI.app.app;
      const omni=app.graph._nodes.find(n=>n.type==='YtonH3TraditionalOmniGenerate');
      const planner=app.graph._nodes.find(n=>n.type==='YtonReplacementPlan');
      const {output}=await app.graphToPrompt();
      return {enabled:omni.widgets.find(w=>w.name==='enable_add_guide').value,
        anchors:output[String(omni.id)].inputs.anchor_images,planner:String(planner.id),
        outputName:app.graph._nodes.find(n=>n.type==='YtonReplacementSegment').outputs[12].name,
        plannerOutputs:planner.outputs.length,parser:String(app.graph._nodes.find(n=>n.type==='YtonReplacementSegment').id),
        prompt:output[String(omni.id)].inputs.prompt};
    });
    check(wired.enabled===true,'saved workflow enables Add Guide');
    check(wired.plannerOutputs===1 && wired.outputName==='替换关键帧' && wired.anchors[0]===wired.parser && wired.anchors[1]===12,'saved workflow connects keyframe payload');
    check(wired.prompt[1]===2,'existing prompt link remains correct');
    return {checks:['processed video and frame counter','C capture and deduplication','image upload','timeline seek','frame stepping','play/pause','config persistence','reopen','small viewport','per-segment isolation','delete','node removal cleanup','full workflow serialization and Add Guide link','two-column cards','numbered marker drag','numeric frame adjustment','marker keyboard adjustment','stale edit invalidation and reupload','source filename download','clipboard upload isolation','drop upload and clear']};
  } finally { await context.close(); }
}
