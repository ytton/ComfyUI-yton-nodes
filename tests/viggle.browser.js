// Start tests/viggle_preview_server.py; use real nodes and real CPU media routes.
async (basePage) => {
  const context=await basePage.context().browser().newContext({viewport:{width:1540,height:1100},acceptDownloads:true});
  const page=await context.newPage(),checks=[],errors=[];
  const check=(value,text)=>{if(!value)throw new Error(text);checks.push(text);};
  page.on("pageerror",error=>errors.push(error.stack || error.message));
  try {
    for(const pattern of ["**/userdata/**","**/settings/**"])
      await page.route(pattern,route=>["POST","PUT","DELETE"].includes(route.request().method())?route.fulfill({json:{}}):route.continue());
    await page.route(/\/(?:api\/)?settings$/,async route=>{
      if(route.request().method()!=="GET")return route.fulfill({json:{}});
      const response=await route.fetch();return route.fulfill({json:{...await response.json(),"Comfy.Workflow.Persist":false,"Comfy.Workflow.AutoSave":"off","Comfy.VueNodes.Enabled":false}});
    });
    await page.route("**/prompt",route=>route.request().method()==="POST"?route.abort():route.continue());
    for(const pattern of ["**/yton/viggle/**","**/view?**","**/upload/image"])
      await page.route(pattern,async route=>{
        const url=new URL(route.request().url());
        await route.fulfill({response:await route.fetch({url:"http://127.0.0.1:8191"+url.pathname.replace(/^\/api/,"")+url.search})});
      });
    await page.goto("http://127.0.0.1:8188/");
    await page.waitForFunction(()=>{
      const app=window.comfyAPI?.app?.app;
      if(!app?.vueAppReady || !app.graphLoadSequence || app.committedGraphLoadSequence!==app.graphLoadSequence || app.pendingGraphLoads.size || !window.LiteGraph?.registered_node_types?.YtonReplacementPlan)return false;
      if(window.viggleReadySequence!==app.graphLoadSequence){window.viggleReadySequence=app.graphLoadSequence;window.viggleReadyTime=performance.now();}
      return performance.now()-window.viggleReadyTime>1000;
    },{},{timeout:60000});
    const definitions=await(await page.request.get("http://127.0.0.1:8191/definitions")).json();
    const config=await(await page.request.get("http://127.0.0.1:8191/config")).json();
    const previous=await(await page.request.get("http://127.0.0.1:8191/previous")).json();
    for(const definition of Object.values(definitions))definition.python_module="custom_nodes.ComfyUI-yton-nodes";
    await page.evaluate(async({definitions,config,previous})=>{
      const app=window.comfyAPI.app.app;
      await app.loadGraphData({version:0.4,nodes:[],links:[],groups:[],config:{},extra:{}});
      await import("/extensions/ComfyUI-yton-nodes/viggle_nodes.js");
      await app.registerNodesFromDefs(definitions);
      const node=LiteGraph.createNode("YtonViggleReplacementPlan");app.graph.add(node);node.pos=[140,150];
      app.canvas.ds.scale=1;app.canvas.ds.offset=[0,0];
      node.widgets.find(widget=>widget.name==="config").value=JSON.stringify(config);node.onConfigure();
      app.canvas.selectNode(node);window.viggleNode=node;
      const parser=LiteGraph.createNode("YtonViggleReplacementSegment"),save=LiteGraph.createNode("YtonReplacementVideoSave");
      app.graph.add(parser);app.graph.add(save);parser.pos=[1500,40];save.pos=[1900,40];
      node.connect(0,parser,0);parser.connect(0,save,0);save.properties.replacementPreview={segments:[previous]};
      window.viggleConfig=()=>JSON.parse(node.widgets.find(widget=>widget.name==="config").value);
    },{definitions,config,previous});
    await page.waitForFunction(()=>document.querySelector('.vv-slider')?.disabled===false);
    const root=page.locator('.vv-panel');
    const sizes=()=>root.locator('.vv-reference .vv-thumb').evaluateAll(items=>items.map(item=>{const r=item.getBoundingClientRect();return {w:r.width,h:r.height};}));
    const before=await sizes();
    check(before.length===4 && before.every(size=>Math.abs(size.h-before[0].h)<1 && Math.abs(size.w-before[0].w)<1),"四个参考槽在部分上传时尺寸一致");
    const png=await(await page.request.get('http://127.0.0.1:8191/view?filename=blue.png&type=input')).body();
    async function drop(selector,name) {
      await root.locator(selector).evaluate((element,{bytes,name})=>{
        const transfer=new DataTransfer();transfer.items.add(new File([new Uint8Array(bytes)],name,{type:"image/png"}));
        element.dispatchEvent(new DragEvent("drop",{bubbles:true,cancelable:true,dataTransfer:transfer}));
      },{bytes:[...png],name});
    }
    await drop('.vv-reference:nth-child(2) .vv-thumb','drop.png');
    await page.waitForFunction(()=>window.viggleConfig().images[1].endsWith('drop.png'));
    check((await sizes()).every((size,i)=>size.w===before[i].w&&size.h===before[i].h),"拖拽上传不改变参考槽尺寸");
    await root.locator('.vv-reference:nth-child(4) .vv-thumb').click();
    await page.evaluate(bytes=>{
      document.activeElement?.blur();
      const data=new DataTransfer();data.items.add(new File([new Uint8Array(bytes)],"paste.png",{type:"image/png"}));
      document.body.dispatchEvent(new ClipboardEvent("paste",{bubbles:true,cancelable:true,clipboardData:data}));
    },[...png]);
    await page.waitForFunction(()=>window.viggleConfig().images[3].endsWith('paste.png'));
    check((await sizes()).every((size,i)=>size.w===before[i].w&&size.h===before[i].h),"选中节点粘贴到指定槽，尺寸保持不变");
    await root.getByRole('button',{name:'关键帧模式',exact:true}).click();
    const slider=root.getByRole('slider',{name:'当前视频帧',exact:true});
    async function lock(frame) {
      await slider.evaluate((element,value)=>{element.value=value;element.dispatchEvent(new Event('input',{bubbles:true}));},frame);
      await root.locator('video').evaluate(video=>!video.seeking || new Promise(resolve=>video.addEventListener('seeked',resolve,{once:true})));
      await page.evaluate(()=>document.activeElement?.blur());await page.keyboard.press('c');
      await root.locator(`.vv-pair[data-frame="${frame}"] .vv-original img`).waitFor();
    }
    for(const frame of [0,10,20,30])await lock(frame);
    check(await root.locator('.vv-pair').count()===4,"C 收集四个关键帧并限制数量");
    const geometry=await root.locator('.vv-pair').first().locator('.vv-thumb').evaluateAll(items=>items.map(item=>({tag:item.tagName,w:item.getBoundingClientRect().width,h:item.getBoundingClientRect().height})));
    check(geometry[1].tag==='DIV'&&geometry[0].w===geometry[1].w&&geometry[0].h===geometry[1].h,"原帧和替换占位框等大，右侧不是上传按钮");
    check(await root.locator('.vv-pair-images button:not(.vv-download)').count()===0,"上传与重叠操作位于标题栏");
    const list=await root.locator('.vv-pairs').evaluate(element=>({height:element.clientHeight,scroll:element.scrollHeight,row:element.firstElementChild.getBoundingClientRect().height,width:getComputedStyle(element,'::-webkit-scrollbar').width}));
    check(list.scroll>list.height && Math.abs(list.height-2*list.row)<8,"关键帧列表最多显示两组高度");
    check(list.width==='3px',"关键帧列表使用三像素滚动条");
    await root.locator('.vv-pairs').evaluate(element=>element.scrollTop=0);
    await root.locator('.vv-original').first().hover();
    const download=root.getByRole('button',{name:'下载第1帧',exact:true});
    await page.waitForFunction(()=>getComputedStyle(document.querySelector('.vv-download')).opacity==='1');
    const relative=await download.evaluate(element=>{const r=element.getBoundingClientRect(),p=element.parentElement.getBoundingClientRect();return {right:p.right-r.right,bottom:p.bottom-r.bottom};});
    check(relative.right<7&&relative.bottom<7,"下载按钮位于原帧右下角");
    const downloaded=page.waitForEvent('download');await download.click();
    check((await downloaded).suggestedFilename()==='source_第1帧.png',"实际下载文件以视频名和帧号命名");
    await drop('.vv-pair[data-frame="0"] .vv-thumb:last-child','keyframe.png');
    await page.waitForFunction(()=>window.viggleConfig().keyframes['0'][0].image.endsWith('keyframe.png'));
    check(true,"替换帧占位框支持拖拽上传");
    const track=await root.locator('.vv-track').evaluate(element=>({height:element.getBoundingClientRect().height,radius:getComputedStyle(element).borderRadius}));
    check(track.height===30&&track.radius==='2px',"帧轨道为方形胶卷长条");
    const marker=root.getByRole('button',{name:'跳到第11帧',exact:true});
    const markerBox=await marker.boundingBox(),trackBox=await root.locator('.vv-track').boundingBox();
    await page.mouse.move(markerBox.x+markerBox.width/2,markerBox.y+markerBox.height/2);await page.mouse.down();
    await page.mouse.move(trackBox.x+trackBox.width*15/35,markerBox.y+markerBox.height/2,{steps:5});await page.mouse.up();
    await page.waitForFunction(()=>window.viggleConfig().keyframes['0'].some(item=>item.frame===15));
    check(true,"拖动帧标记可调整关键帧位置");
    await root.getByRole('combobox',{name:'当前片段',exact:true}).selectOption('1');
    await page.waitForFunction(()=>document.querySelector('.vv-counter')?.textContent.includes('/ 36'));
    await lock(0);await root.getByRole('button',{name:'使用上一段重叠帧',exact:true}).click();
    await page.waitForFunction(()=>window.viggleConfig().keyframes['1']?.[0].source==='previous');
    check(await root.locator('.vv-thumb-label').filter({hasText:'上一段重叠帧'}).count()===1,"一键取上一段对应重叠帧并直接填入");
    check(await page.locator('dialog[open]').count()===0,"选帧与使用重叠帧均不打开弹窗");
    await root.getByRole('button',{name:'1080p',exact:true}).click();
    await page.waitForFunction(()=>window.viggleConfig().resolution==='1080p' && document.querySelector('.vv-panel video')?.videoHeight===1088);
    check(await root.getByRole('button',{name:'1080p',exact:true}).getAttribute('aria-pressed')==='true',"1080p 可选并保持选中状态");
    check(await root.locator('video').evaluate(video=>video.videoWidth===1792 && video.videoHeight===1088),"1080p 预览沿用原视频比例并对齐到 32 的倍数");
    await page.screenshot({path:'F:/ComfyUI/ComfyUI/custom_nodes/ComfyUI-yton-nodes/.artifacts/viggle-node.png',fullPage:true});
    check(!errors.length,`浏览器无运行错误：${errors.join(';')}`);
    return {checks,errors};
  } finally {await context.close();}
}
