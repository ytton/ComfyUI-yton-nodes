// Run with Playwright browser_run_code_unsafe after starting replacement_preview_server.py.
async (basePage) => {
  const context = await basePage.context().browser().newContext({viewport:{width:1660,height:1050}});
  const page = await context.newPage();
  const errors=[];
  let phase="setup";
  page.on("pageerror",error=>{if(/replacement_/i.test(error.stack||"")) errors.push(error.message);});
  const check=(value,message)=>{if(!value)throw new Error(message);};
  try {
    await page.route("**/prompt",route=>route.request().method()==="POST" ? route.abort() : route.continue());
    for(const pattern of ["**/userdata/**","**/settings/**"]) await page.route(pattern,route=>["POST","PUT","DELETE"].includes(route.request().method()) ? route.fulfill({status:200,json:{}}) : route.continue());
    for(const pattern of ["**/yton/replacement/**","**/yton/llm/**","**/view?**","**/upload/image"])
      await page.route(pattern,async route=>{
        const url=new URL(route.request().url());
        const response=await route.fetch({url:"http://127.0.0.1:8190"+url.pathname.replace(/^\/api/,"")+url.search});
        await route.fulfill({response});
      });
    await page.goto("http://127.0.0.1:8188/");
    await page.waitForFunction(()=>{try{
      const app=window.comfyAPI?.app?.app;
      return app?.vueAppReady && app.graphLoadSequence>0 && app.committedGraphLoadSequence===app.graphLoadSequence
        && app.pendingGraphLoads.size===0 && app.extensions.some(e=>e.name==="yton.character-replacement");
    }catch{return false;}});
    const defs=await(await page.request.get("http://127.0.0.1:8190/definitions")).json();
    const config=await(await page.request.get("http://127.0.0.1:8190/config")).json();
    for(const definition of Object.values(defs))definition.python_module="custom_nodes.ComfyUI-yton-nodes";
    await page.evaluate(async ({defs,config})=>{
      const {app}=window.comfyAPI.app;
      await app.registerNodesFromDefs(defs);
      app.graph.clear();
      const llm=LiteGraph.createNode("YtonLLMConnector"), node=LiteGraph.createNode("YtonCharacterReplacement"), save=LiteGraph.createNode("YtonReplacementVideoSave");
      for(const n of [llm,node,save]) app.graph.add(n);
      llm.pos=[20,150];node.pos=[370,150];save.pos=[1160,150];
      node.widgets.find(w=>w.name==="config").value=JSON.stringify(config);node.onConfigure?.();
      llm.connect(0,node,node.inputs.findIndex(i=>i.name==="llm"));
      for(const [output,input] of [[1,"video"],[7,"current"],[8,"total"]]) node.connect(output,save,save.inputs.findIndex(i=>i.name===input));
      app.canvas.ds.scale=.9;app.canvas.ds.offset=[0,10];
      window.replacementTest={llm,node,save};
    },{defs,config});
    const prefixTemplate="video/人物替换/%date:yyyy-MM-dd%/片段";
    await page.getByLabel("保存目录与前缀",{exact:true}).fill(prefixTemplate);
    await page.getByLabel("保存目录与前缀",{exact:true}).press("Tab");
    const prefixResult=await page.evaluate(async()=>{
      const {app}=window.comfyAPI.app, {save}=window.replacementTest;
      const prefix=save.widgets.find(w=>w.name==="filename_prefix"), now=new Date();
      const date=[now.getFullYear(),String(now.getMonth()+1).padStart(2,"0"),String(now.getDate()).padStart(2,"0")].join("-");
      return {template:prefix.value,submitted:(await app.graphToPrompt()).output[save.id].inputs.filename_prefix,date};
    });
    check(prefixResult.template===prefixTemplate,"save prefix keeps its editable date template");
    check(prefixResult.submitted===`video/人物替换/${prefixResult.date}/片段`,"save prefix expands date before submitting to Windows");
    await page.getByLabel("查看片段提示词",{exact:true}).locator("option").filter({hasText:"第 1 / 2 段"}).waitFor({state:"attached"});
    await page.locator(".yr-pgs-rich-editor").waitFor();
    check(await page.locator(".yr-image-slot").count()===6,"six image slots");
    check(await page.locator(".yr-image-slot img").first().evaluate(e=>getComputedStyle(e).objectFit)==="contain","reference images use contain");
    check(await page.locator(".yr-duration").innerText().then(t=>t.includes("39 帧")),"H3 duration is read-only frames");
    await page.getByRole("button",{name:"查看提示词优化 Skill",exact:true}).click();
    const skill=page.locator(".yr-skill-dialog");
    await page.waitForFunction(()=>document.querySelector('.yr-skill-content')?.value.startsWith("你是视频人物替换提示词编写助手"));
    const actualSkill=await(await page.request.get("http://127.0.0.1:8190/yton/replacement/skill")).json();
    check(await skill.getByLabel("实际使用的优化 Skill",{exact:true}).inputValue()===actualSkill.skill,"viewer shows actual backend skill");
    check((await skill.innerText()).includes("等间隔抽取六帧"),"viewer explains input processing");
    check(await skill.getByLabel("实际使用的优化 Skill",{exact:true}).evaluate(e=>e.readOnly),"skill is view-only");
    await page.keyboard.press("Escape");
    await skill.waitFor({state:"detached"});
    await page.getByRole("button",{name:"使用当前段抽帧和参考图片优化提示词",exact:true}).click();
    await page.getByText("优化完成",{exact:true}).waitFor();
    check((await page.locator(".yr-pgs-rich-editor").innerText()).includes("【同步要求】"),"manual vision optimization returns prompt");
    await page.getByRole("button",{name:"编辑",exact:true}).click();
    phase="original PGS editor";
    const dialog=page.locator(".yr-pgs-ov");
    await dialog.locator(".yr-pgs-seg-item").first().waitFor();
    const mode=dialog.locator("select").filter({has:page.locator('option[value="minimaxh3"]')});
    const length=dialog.locator("select").filter({has:page.locator('option[value="1.6250"]')});
    check(await length.locator("option").count()===31,"original PGS H3 frame options");
    await mode.selectOption("none");
    await dialog.locator("select").filter({has:page.locator('option[value="2"]')}).selectOption("2");
    await dialog.locator("select").filter({has:page.locator('option[value="22"]')}).selectOption("0");
    await dialog.getByRole("button",{name:"保存",exact:true}).click();
    await dialog.waitFor({state:"detached"});
    await page.getByRole("button",{name:"下一段",exact:true}).click();
    check((await page.locator(".yr-duration").innerText()).includes("24 帧"),"tail displays actual frames");
    const independentPrompts=await page.evaluate(()=>{
      const config=JSON.parse(window.replacementTest.node.widgets.find(w=>w.name==="config").value);
      return {original:config.prompts,optimized:config.optimized};
    });
    await page.getByLabel("全段共用提示词",{exact:true}).check();
    check(await page.getByLabel("查看片段提示词",{exact:true}).isDisabled(),"shared prompts disable segment selection");
    for(const name of ["上一段","下一段"])check(await page.getByRole("button",{name,exact:true}).isDisabled(),"shared prompts disable "+name);
    await page.getByRole("button",{name:"原始要求",exact:true}).click();
    await page.locator(".yr-pgs-rich-editor").fill("将@图片3的人物替换视频中的主体。");
    await page.getByLabel("全段共用提示词",{exact:true}).uncheck();
    check(await page.getByLabel("查看片段提示词",{exact:true}).isEnabled(),"independent prompts restore segment selection");
    const restoredPrompts=await page.evaluate(()=>{
      const config=JSON.parse(window.replacementTest.node.widgets.find(w=>w.name==="config").value);
      const {shared,...original}=config.prompts;
      return {original,optimized:config.optimized};
    });
    check(JSON.stringify(restoredPrompts)===JSON.stringify(independentPrompts),"editing shared prompts preserves independent originals and optimizations");
    await page.getByRole("button",{name:"上一段",exact:true}).click();
    await page.getByLabel("全段共用提示词",{exact:true}).check();
    check((await page.evaluate(()=>JSON.parse(window.replacementTest.node.widgets.find(w=>w.name==="config").value).prompts.shared)).includes("@图片3"),"shared prompt survives switching scopes and segments");
    check(await page.locator('.yr-pgs-rich-editor .yr-pgs-token[data-token="@图片3"]').count()===1,"Chinese reference alias renders as a chip next to Chinese prose");
    await page.getByRole("button",{name:"切换纯文本与富文本",exact:true}).click();
    check((await page.locator(".yr-rich-host textarea").inputValue()).includes("<Picture 2>的人物"),"plain text resolves reference identity and retains surrounding prose");
    await page.getByRole("button",{name:"切换纯文本与富文本",exact:true}).click();
    await page.getByRole("button",{name:"预览当前段送给 LLM 的抽帧拼图",exact:true}).click();
    await page.locator(".yr-frames-dialog img").evaluate(image=>new Promise((resolve,reject)=>{
      if(image.complete && image.naturalWidth)return resolve();image.onload=resolve;image.onerror=()=>reject(new Error("contact sheet preview failed"));
    }));
    await page.locator(".yr-frames-dialog").getByRole("button",{name:"关闭",exact:true}).click();
    await page.getByRole("button",{name:"插入参考素材引用",exact:true}).click();
    check((await page.locator(".yr-pgs-alias-menu").innerText()).includes("@图片3 → <Picture 2>"),"aliases follow filled image slots");
    await page.keyboard.press("Escape");
    const png="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j14kAAAAASUVORK5CYII=";
    phase="image drag upload";
    await page.locator(".yr-image-slot").nth(1).evaluate((element,png)=>{
      const file=new File([Uint8Array.from(atob(png),c=>c.charCodeAt(0))],"drop.png",{type:"image/png"});
      const transfer=new DataTransfer();transfer.items.add(file);
      element.dispatchEvent(new DragEvent("drop",{bubbles:true,cancelable:true,dataTransfer:transfer}));
    },png);
    await page.waitForFunction(()=>JSON.parse(window.replacementTest.node.widgets.find(w=>w.name==="config").value).images[1].endsWith("drop.png"));
    phase="image paste upload";
    await page.evaluate(png=>{
      const {app}=window.comfyAPI.app;const {node}=window.replacementTest;
      app.canvas.selectNode(node);
      document.activeElement?.blur();
      const transfer=new DataTransfer();transfer.items.add(new File([Uint8Array.from(atob(png),c=>c.charCodeAt(0))],"paste.png",{type:"image/png"}));
      const event=new ClipboardEvent("paste",{bubbles:true,cancelable:true,clipboardData:transfer});
      window.replacementPasteDebug={sameGraph:node.graph===app.canvas.graph,selected:Object.values(app.canvas.selected_nodes||{}).map(n=>({id:n.id,same:n===node})),files:event.clipboardData.files.length};
      document.dispatchEvent(event);
      window.replacementPasteDebug.prevented=event.defaultPrevented;
    },png);
    await page.waitForFunction(()=>JSON.parse(window.replacementTest.node.widgets.find(w=>w.name==="config").value).images.some(name=>name.endsWith("paste.png")));
    phase="image picker upload";
    const picker=page.waitForEvent("filechooser");
    await page.getByRole("button",{name:"选择图片 6",exact:true}).click();
    await(await picker).setFiles({name:"picker.png",mimeType:"image/png",buffer:Buffer.from(png,"base64")});
    await page.waitForFunction(()=>JSON.parse(window.replacementTest.node.widgets.find(w=>w.name==="config").value).images[5].endsWith("picker.png"));
    phase="video picker upload";
    const source=await(await page.request.get("http://127.0.0.1:8190/view?filename=source.mp4&type=input")).body();
    const chooseVideo=page.waitForEvent("filechooser");
    await page.getByRole("button",{name:"选择视频文件",exact:true}).click();
    await(await chooseVideo).setFiles({name:"video-picker.mp4",mimeType:"video/mp4",buffer:source});
    await page.waitForFunction(()=>JSON.parse(window.replacementTest.node.widgets.find(w=>w.name==="config").value).video.endsWith("video-picker.mp4"));
    const bytes=source.toString("base64");
    phase="video paste upload";
    await page.evaluate(bytes=>{
      document.activeElement?.blur();
      const transfer=new DataTransfer();transfer.items.add(new File([Uint8Array.from(atob(bytes),c=>c.charCodeAt(0))],"video-paste.mp4",{type:"video/mp4"}));
      document.dispatchEvent(new ClipboardEvent("paste",{bubbles:true,cancelable:true,clipboardData:transfer}));
    },bytes);
    await page.waitForFunction(()=>JSON.parse(window.replacementTest.node.widgets.find(w=>w.name==="config").value).video.endsWith("video-paste.mp4"));
    phase="video drag feedback";
    const dragFeedback=await page.locator(".yr-video-slot").evaluate(element=>{
      const root=element.closest(".yton-replacement-panel");
      const transfer=new DataTransfer();transfer.items.add(new File(["video"],"hover.mp4",{type:"video/mp4"}));
      const over=target=>target.dispatchEvent(new DragEvent("dragover",{bubbles:true,cancelable:true,dataTransfer:transfer}));
      over(root.querySelector(".yr-prompt"));
      const entered=element.classList.contains("drag-over") && getComputedStyle(element.querySelector(".yr-video-drop-hint")).display==="flex";
      element.dispatchEvent(new DragEvent("dragleave",{bubbles:true,relatedTarget:element.querySelector("video")}));
      const childMove=element.classList.contains("drag-over");
      root.dispatchEvent(new DragEvent("dragleave",{bubbles:true,relatedTarget:document.body}));
      const exited=!element.classList.contains("drag-over") && !root.classList.contains("yr-drag-over");
      over(element);
      document.dispatchEvent(new DragEvent("dragend",{bubbles:true}));
      const cancelled=!element.classList.contains("drag-over");
      const text=new DataTransfer();text.setData("text/plain","not a file");
      root.dispatchEvent(new DragEvent("dragover",{bubbles:true,cancelable:true,dataTransfer:text}));
      const textIgnored=!element.classList.contains("drag-over");
      return {entered,childMove,exited,cancelled,textIgnored,label:element.querySelector(".yr-video-drop-hint strong").textContent};
    });
    check(dragFeedback.entered && dragFeedback.childMove,"video drag highlights destination across the panel without flickering between children");
    check(dragFeedback.exited && dragFeedback.cancelled && dragFeedback.textIgnored,"video drag feedback clears on exit and cancellation and ignores text");
    check(dragFeedback.label==="松开替换视频","drop hint describes replacement of an existing video");
    phase="video drag upload";
    await page.locator(".yr-video-slot").evaluate((element,bytes)=>{
      const transfer=new DataTransfer();transfer.items.add(new File([Uint8Array.from(atob(bytes),c=>c.charCodeAt(0))],"video-drop.mp4",{type:"video/mp4"}));
      element.dispatchEvent(new DragEvent("drop",{bubbles:true,cancelable:true,dataTransfer:transfer}));
    },bytes);
    await page.waitForFunction(()=>JSON.parse(window.replacementTest.node.widgets.find(w=>w.name==="config").value).video.endsWith("video-drop.mp4"));
    check(await page.locator(".yr-video-slot.drag-over").count()===0,"drop clears video drag highlight");
    phase="merged playback";
    const saved=await(await page.request.get("http://127.0.0.1:8190/saved")).json();
    await page.evaluate(saved=>window.replacementTest.save.onExecuted({replacement_saved:[saved]}),saved);
    await page.locator(".yr-save>video").evaluate(video=>new Promise((resolve,reject)=>{
      if(video.readyState>=1)return resolve();video.onloadedmetadata=()=>resolve();video.onerror=()=>reject(new Error("merged preview failed"));
    }));
    const playback=await page.locator(".yr-save>video").evaluate(async v=>{v.muted=true;await v.play();return {duration:v.duration,playing:!v.paused};});
    check(playback.playing,"merged preview actually plays");
    check(await page.locator(".yr-saved-clips button").count()===saved.segments.length,"clip list contains only individual segments");
    check(await page.locator(".yr-saved-clips").getByRole("button",{name:"完整视频",exact:true}).count()===0,"merged video is not a segment card");
    await page.locator(".yr-saved-clips").getByRole("button",{name:"片段 1",exact:true}).click();
    check(await page.locator(".yr-save>video").evaluate(v=>new URL(v.src).searchParams.get("filename"))===saved.segments[0].filename,"clicking segment changes main preview");
    await page.locator(".yr-save-heading").getByRole("button",{name:"返回完整视频",exact:true}).click();
    check(await page.locator(".yr-save>video").evaluate(v=>new URL(v.src).searchParams.get("filename"))===saved.merged.filename,"heading return icon restores complete video");
    const serial=await page.evaluate(async()=>{
      const {app}=window.comfyAPI.app;
      const graph=app.graph.serialize();
      await app.loadGraphData(graph);
      return graph;
    });
    await page.locator(".yr-image-slot img").nth(4).waitFor();
    check(serial.nodes.find(n=>n.type==="YtonCharacterReplacement").outputs.length===9,"configuration outputs include width, height, frame count and duration");
    check(!serial.nodes.find(n=>n.type==="YtonCharacterReplacement").widgets_values.includes(0),"index has no editable widget");
    check(serial.nodes.find(n=>n.type==="YtonCharacterReplacement").inputs.some(i=>i.name==="index" && i.type==="INT"),"index is a normal INT input");
    const geometry=await page.locator(".yton-replacement-panel:not(.yr-save):not(.yr-connector)").evaluate(panel=>({width:panel.clientWidth,scroll:panel.scrollWidth,overflow:getComputedStyle(panel.parentElement).overflow}));
    check(geometry.width>=700 && geometry.scroll===geometry.width,"default panel has no horizontal overflow");
    check(geometry.overflow==="visible","media column can extend into the unused left socket area");
    const layout=await page.locator(".yton-replacement-panel:not(.yr-save):not(.yr-connector)").evaluate(panel=>{const left=panel.querySelector(".yr-media"),right=panel.querySelector(".yr-prompt");return {lift:right.getBoundingClientRect().top-left.getBoundingClientRect().top,controls:left.contains(panel.querySelector(".yr-config-controls")),editor:!right.querySelector(".yr-config-controls")};});
    check(layout.lift>=100 && layout.controls && layout.editor,"media starts above prompt and generation controls appear below reference images");
    check(await page.locator(".yr-save").evaluate(panel=>getComputedStyle(panel.parentElement).overflow)==="hidden","save panel shell has no stray scrollbar");
    await page.screenshot({path:"C:/Users/YuanTong/AppData/Local/Temp/replacement-implemented.png"});
    check(!errors.length,errors.join("; "));
    return {checks:"uploads via picker, drop and paste; video drag feedback and cleanup; PGS aliases; shared prompts; optimization; frame plans; serialized settings; playable merge; segment-only cards and return to complete preview",playback,geometry,screenshot:"C:/Users/YuanTong/AppData/Local/Temp/replacement-implemented.png"};
  } catch(error) {
    const details=await page.evaluate(()=>({panels:document.querySelectorAll(".yton-replacement-panel").length,paste:window.replacementPasteDebug,status:[...document.querySelectorAll(".yr-status")].map(e=>e.textContent),body:document.body.innerText.slice(-1200)}));
    throw new Error(`${phase}: ${error.message}\n${JSON.stringify(details)}`);
  } finally {await context.close();}
}
