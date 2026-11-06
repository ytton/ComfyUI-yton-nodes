// Start tests/viggle_preview_server.py. Uses temporary media and an isolated workflow.
async (basePage) => {
  const context=await basePage.context().browser().newContext({viewport:{width:1540,height:1100}});
  const page=await context.newPage(),checks=[],errors=[];
  const check=(value,message)=>{if(!value)throw new Error(message);checks.push(message);};
  try {
    for(const pattern of ["**/userdata/**","**/settings/**"])
      await page.route(pattern,route=>["POST","PUT","DELETE"].includes(route.request().method())?route.fulfill({json:{}}):route.continue());
    await page.route(/\/(?:api\/)?settings$/,async route=>{
      if(route.request().method()!=="GET")return route.fulfill({json:{}});
      const response=await route.fetch();return route.fulfill({json:{...await response.json(),"Comfy.Workflow.Persist":false,"Comfy.Workflow.AutoSave":"off","Comfy.VueNodes.Enabled":false}});
    });
    await page.route("**/prompt",route=>route.request().method()==="POST"?route.abort():route.continue());
    for(const pattern of ["**/yton/viggle/**","**/yton/replacement/**","**/view?**","**/upload/image"])
      await page.route(pattern,async route=>{
        const url=new URL(route.request().url());
        await route.fulfill({response:await route.fetch({url:"http://127.0.0.1:8191"+url.pathname.replace(/^\/api/,"")+url.search})});
      });
    await page.goto("http://127.0.0.1:8188/");
    await page.waitForFunction(()=>{
      const app=window.comfyAPI?.app?.app;
      return app?.vueAppReady && app.graphLoadSequence && app.committedGraphLoadSequence===app.graphLoadSequence
        && !app.pendingGraphLoads.size && window.LiteGraph?.registered_node_types?.YtonViggleReplacementPlan;
    },{},{timeout:60000});
    const definitions=await(await page.request.get("http://127.0.0.1:8191/definitions")).json();
    const config=await(await page.request.get("http://127.0.0.1:8191/config")).json();
    config.shared=false;config.auto=false;
    config.prompts={"0":"将@视频的人物替换为@图片1。\n\n保留原动作。\n","1":"第二段使用@图片3。"};
    config.optimized={"0":{text:"用 <Picture 1> 替换 <Video 1> 中的人物。\n保持动作。",signature:"browser-check"},
      "2":{text:"第三段的优化结果",signature:"third"},shared:{text:"全段共用的优化结果",signature:"shared"}};
    for(const definition of Object.values(definitions))definition.python_module="custom_nodes.ComfyUI-yton-nodes";
    await page.evaluate(async({definitions,config})=>{
      const app=window.comfyAPI.app.app;
      await app.loadGraphData({version:0.4,nodes:[],links:[],groups:[],config:{},extra:{}});
      await app.registerNodesFromDefs(definitions);
      const node=LiteGraph.createNode("YtonViggleReplacementPlan");app.graph.add(node);node.pos=[140,150];
      app.canvas.ds.scale=1;app.canvas.ds.offset=[0,0];
      node.widgets.find(widget=>widget.name==="config").value=JSON.stringify(config);node.onConfigure();
      window.vigglePromptNode=node;
      window.promptConfig=()=>JSON.parse(node.widgets.find(widget=>widget.name==="config").value);
    },{definitions,config});
    await page.waitForFunction(()=>document.querySelector('.vv-slider')?.disabled===false);
    page.on('pageerror',error=>errors.push(error.message));
    const root=page.locator('.vv-panel');
    const toggle=root.getByRole('button',{name:'切换纯文本与富文本',exact:true});
    const original=root.getByLabel('Viggle 原始要求',{exact:true});
    check(await toggle.innerText()==='纯文本' && await original.evaluate(e=>e.isContentEditable),'默认富文本显示纯文本切换按钮');
    const size=await original.boundingBox();
    await toggle.click();
    check(await original.inputValue()==="将<Video 1>的人物替换为<Picture 1>。\n\n保留原动作。\n",'纯文本展示实际引用标签并保留空行');
    const plainSize=await original.boundingBox();
    check(Math.abs(size.width-plainSize.width)<2 && Math.abs(size.height-plainSize.height)<2,'两种模式使用相同的输入框尺寸');
    check(await root.getByRole('button',{name:'@ 引用',exact:true}).isDisabled(),'纯文本关闭引用工具');
    await original.fill('将<Video 1>的人物替换为<Picture 1>。\n用户补充。\n');
    check(await page.evaluate(()=>window.promptConfig().prompts['0'])==="将@视频的人物替换为@图片1。\n用户补充。\n",'纯文本编辑保留素材映射并同步存储');
    check(await page.evaluate(()=>window.promptConfig().optimized['0'].text)===config.optimized['0'].text,'修改原始要求保留已有优化结果');
    await toggle.click();
    check(await original.locator('.yr-pgs-token').count()===2 && await toggle.innerText()==='纯文本','切回富文本恢复引用标签');
    check(await root.getByRole('button',{name:'@ 引用',exact:true}).isEnabled(),'富文本恢复引用工具');
    await root.getByRole('combobox',{name:'当前片段',exact:true}).selectOption('1');
    await page.waitForFunction(()=>document.querySelector('[aria-label="Viggle 原始要求"]')?.textContent.includes('第二段'));
    await toggle.click();
    check(await original.inputValue()==='第二段使用<Picture 2>。','切换片段沿用当前文本模式并更新该段提示词');
    await root.getByRole('button',{name:'本段优化',exact:true}).click();
    const optimized=root.getByLabel('Viggle 优化提示词',{exact:true});
    check(await optimized.getAttribute('readonly')!==null,'没有优化结果时纯文本保持只读');
    await root.getByRole('combobox',{name:'当前片段',exact:true}).selectOption('0');
    await page.waitForFunction(()=>document.querySelector('textarea[aria-label="Viggle 优化提示词"]')?.value.includes('保持动作'));
    await optimized.fill('用 <Picture 1> 替换 <Video 1>。\n保持表情。');
    check(await page.evaluate(()=>window.promptConfig().optimized['0'].text)==='用 @图片1 替换 @视频。\n保持表情。','优化提示词也支持纯文本编辑');
    await toggle.click();
    const copied=await optimized.evaluate(editor=>{
      editor.focus();const range=document.createRange();range.selectNodeContents(editor);
      getSelection().removeAllRanges();getSelection().addRange(range);
      const data=new DataTransfer();editor.dispatchEvent(new ClipboardEvent('copy',{clipboardData:data,bubbles:true,cancelable:true}));
      return data.getData('text/plain');
    });
    check(copied==='用 <Picture 1> 替换 <Video 1>。\n保持表情。','Viggle 富文本复制不在引用标签两侧插入换行');
    const saved=await page.evaluate(()=>JSON.stringify(window.promptConfig().optimized));
    const retained=async message=>check(await page.evaluate(()=>JSON.stringify(window.promptConfig().optimized))===saved,message);
    await root.getByRole('button',{name:'480p',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.vv-panel video')?.videoHeight===480);
    await retained('调整分辨率保留所有片段和共用优化结果');
    await root.getByRole('button',{name:'9:16',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.vv-panel video')?.videoHeight===864);
    await retained('调整画面比例保留优化结果');
    await root.getByRole('combobox',{name:'图片缩放',exact:true}).selectOption('0.5');
    await retained('调整图片缩放保留优化结果');
    await root.getByRole('button',{name:'关键帧模式',exact:true}).click();
    await retained('切换素材模式保留优化结果');
    await root.getByRole('button',{name:'锁定当前关键帧（C）',exact:true}).click();
    await retained('新增关键帧保留优化结果');
    await root.getByRole('button',{name:'删除第1帧',exact:true}).click();
    await retained('删除关键帧保留优化结果');
    await root.getByRole('button',{name:'参考图模式',exact:true}).click();
    await root.getByRole('button',{name:'移除图片3',exact:true}).click();
    await retained('移除参考图片保留优化结果');
    await root.getByLabel('全段共用提示词',{exact:true}).check();
    check(await optimized.textContent()==='全段共用的优化结果','共用模式继续显示单独保存的共用优化结果');
    await root.getByLabel('全段共用提示词',{exact:true}).uncheck();
    await retained('切换共用与分段模式保留各自的优化结果');
    await root.getByRole('button',{name:'编辑 / 分段',exact:true}).click();
    const dialog=page.locator('.yr-pgs-ov');
    await dialog.locator('.yr-pgs-seg-item').first().waitFor();
    await dialog.getByTitle('等比锁定',{exact:true}).click();
    await dialog.getByLabel('参考视频压缩宽度',{exact:true}).fill('80');
    await dialog.getByLabel('参考视频压缩高度',{exact:true}).fill('48');
    await dialog.getByRole('button',{name:'保存',exact:true}).click();
    await dialog.waitFor({state:'detached'});
    await retained('保存视频编辑配置保留全部优化提示词');
    check((await optimized.textContent()).includes('保持表情'),'编辑器保存后优化结果仍在输入框中');
    const videoBytes=await(await page.request.get('http://127.0.0.1:8191/view?filename=source.mp4&type=input')).body();
    await root.locator('.vv-media').evaluate((target,bytes)=>{
      const data=new DataTransfer();data.items.add(new File([new Uint8Array(bytes)],'another-source.mp4',{type:'video/mp4'}));
      target.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:data}));
    },[...videoBytes]);
    await page.waitForFunction(()=>window.promptConfig().video.endsWith('another-source.mp4'));
    await retained('重新上传视频保留全部优化提示词');
    await page.screenshot({path:'F:/ComfyUI/ComfyUI/custom_nodes/ComfyUI-yton-nodes/.artifacts/viggle-prompt-editor.png',fullPage:true});
    check(!errors.length,`浏览器无运行错误：${errors.join(';')}`);
    return {checks,errors};
  } finally {await page.unrouteAll({behavior:'wait'});await context.close();}
}
