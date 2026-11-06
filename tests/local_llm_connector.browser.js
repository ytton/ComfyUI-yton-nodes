// Real ComfyUI nodes and CPU task routes, with inference isolated in the fixture.
async (basePage) => {
  const context=await basePage.context().browser().newContext({viewport:{width:1540,height:1100}});
  const page=await context.newPage(),checks=[],errors=[],requests=[];
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
    for(const pattern of ["**/yton/viggle/**","**/yton/replacement/**","**/yton/llm/**","**/yton/prompt-optimizer/llama","**/view?**"])
      await page.route(pattern,async route=>{
        const url=new URL(route.request().url());
        if(url.pathname.endsWith('/optimize'))requests.push({path:url.pathname,body:route.request().postDataJSON()});
        await route.fulfill({response:await route.fetch({url:"http://127.0.0.1:8191"+url.pathname.replace(/^\/api/,"")+url.search})});
      });
    await page.goto("http://127.0.0.1:8188/");
    await page.waitForFunction(()=>{
      const app=window.comfyAPI?.app?.app;
      if(!app?.vueAppReady || !app.graphLoadSequence || app.committedGraphLoadSequence!==app.graphLoadSequence || app.pendingGraphLoads.size || !window.LiteGraph?.registered_node_types?.YtonReplacementPlan)return false;
      if(window.llmReadySequence!==app.graphLoadSequence){window.llmReadySequence=app.graphLoadSequence;window.llmReadyTime=performance.now();}
      return performance.now()-window.llmReadyTime>1000;
    },{},{timeout:60000});
    const get=async path=>(await page.request.get("http://127.0.0.1:8191/"+path)).json();
    const definitions=await get('definitions'),viggle=await get('config'),replacement=await get('replacement-config');
    const callOffset=(await get('llm-calls')).length;
    for(const definition of Object.values(definitions))definition.python_module="custom_nodes.ComfyUI-yton-nodes";
    await page.evaluate(async({definitions,viggle,replacement})=>{
      const app=window.comfyAPI.app.app;
      await app.loadGraphData({version:0.4,nodes:[],links:[],groups:[],config:{},extra:{}});
      await import("/extensions/ComfyUI-yton-nodes/viggle_nodes.js");
      await app.registerNodesFromDefs(definitions);
      const local=LiteGraph.createNode('YtonLocalLLMConnector'),remote=LiteGraph.createNode('YtonLLMConnector');
      const planner=LiteGraph.createNode('YtonViggleReplacementPlan'),character=LiteGraph.createNode('YtonReplacementPlan');
      for(const node of [local,remote,planner,character])app.graph.add(node);
      local.pos=[70,100];remote.pos=[70,390];planner.pos=[470,100];character.pos=[1500,100];
      app.canvas.ds.scale=.9;app.canvas.ds.offset=[0,0];
      planner.widgets.find(w=>w.name==='config').value=JSON.stringify(viggle);planner.onConfigure();
      character.widgets.find(w=>w.name==='config').value=JSON.stringify(replacement);character.onConfigure();
      local.connect(0,planner,planner.inputs.findIndex(i=>i.name==='llm'));
      local.connect(0,character,character.inputs.findIndex(i=>i.name==='llm'));
      window.connectorNodes={local,remote,planner,character};
    },{definitions,viggle,replacement});
    const root=page.locator('.yr-local-connector');
    await root.locator('.yton-ai-model-options button').first().waitFor({state:'attached'});
    check((await root.locator('.yton-ai-model-menu summary').textContent()).includes('请选择'),"新节点不自动选中模型");
    await root.locator('summary').click();
    check(await root.locator('.yton-ai-model-options').evaluate(menu=>menu.matches(':popover-open')),"模型下拉使用顶层弹层");
    const geometry=await root.evaluate(element=>({panel:element.getBoundingClientRect().toJSON(),menu:element.querySelector('.yton-ai-model-options').getBoundingClientRect().toJSON(),overflow:getComputedStyle(element.parentElement).overflow}));
    check(geometry.menu.bottom>geometry.panel.bottom && geometry.overflow==='hidden',"模型菜单超出面板仍可见，保留节点裁切");
    await root.getByRole('button',{name:'vision-b.gguf',exact:true}).click();
    check(await page.evaluate(()=>window.connectorNodes.local.widgets.find(w=>w.name==='model_name').value)==='vision-b.gguf',"选择 GGUF 写入工作流参数");
    await root.getByRole('button',{name:'本地推理设置',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'llama.cpp 推理设置'});
    await dialog.getByRole('spinbutton',{name:'温度',exact:true}).fill('0.25');
    await dialog.getByRole('spinbutton',{name:'最大输出 Token',exact:true}).fill('1024');
    await dialog.getByRole('button',{name:'保存',exact:true}).click();
    check(await page.evaluate(()=>JSON.parse(window.connectorNodes.local.widgets.find(w=>w.name==='options_json').value).temperature)===.25,"齿轮设置保存本地采样参数");
    const saved=await page.evaluate(()=>window.connectorNodes.local.serialize());
    await page.evaluate(saved=>{
      const app=window.comfyAPI.app.app,{local,planner,character}=window.connectorNodes;
      app.graph.remove(local);
      const restored=LiteGraph.createNode('YtonLocalLLMConnector');app.graph.add(restored);restored.configure({...saved,id:restored.id});
      restored.connect(0,planner,planner.inputs.findIndex(i=>i.name==='llm'));
      restored.connect(0,character,character.inputs.findIndex(i=>i.name==='llm'));
      window.connectorNodes.local=restored;
    },saved);
    await page.waitForFunction(()=>document.querySelector('.yr-local-connector summary')?.textContent==='vision-b.gguf');
    check(await page.evaluate(()=>JSON.parse(window.connectorNodes.local.widgets.find(w=>w.name==='options_json').value).max_tokens)===1024,"工作流重建恢复模型与参数");
    await page.waitForFunction(()=>document.querySelector('.vv-counter')?.textContent.includes('/ 36'));
    const viggleRoot=page.locator('.vv-panel');
    const characterRoot=page.locator('.yton-replacement-panel').filter({has:page.locator('.yr-prompt')});
    const optimize=async(root,name)=>{
      const response=page.waitForResponse(response=>response.url().endsWith('/optimize') && response.request().method()==='POST');
      await root.getByRole('button',{name,exact:true}).evaluate(button=>button.click());
      const result=await response;check(result.ok(),'手动优化请求成功：'+result.url().split('/').slice(-2).join('/'));
    };
    await optimize(viggleRoot,'优化当前段提示词');
    await page.waitForFunction(()=>JSON.parse(window.connectorNodes.planner.widgets.find(w=>w.name==='config').value).optimized['0']?.text.includes('本地测试'));
    await optimize(characterRoot,'使用当前段抽帧和参考图片优化提示词');
    await page.waitForFunction(()=>JSON.parse(window.connectorNodes.character.widgets.find(w=>w.name==='config').value).optimized['0']?.text.includes('本地测试'));
    check(requests.slice(0,2).every(request=>request.body.connection.kind==='local' && request.body.connection.model_name==='vision-b.gguf'),"两种配置器均传递本地连接器配置");
    const calls=(await get('llm-calls')).slice(callOffset);
    check(calls.length===2 && calls.every(call=>call.options.temperature===.25 && call.media_count===3 && call.has_media),"手动接口实际使用节点参数和三张图片调用本地运行时");
    await page.evaluate(()=>{
      const {remote,planner,character}=window.connectorNodes;
      for(const node of [planner,character])remote.connect(0,node,node.inputs.findIndex(i=>i.name==='llm'));
    });
    await optimize(viggleRoot,'优化当前段提示词');
    await page.waitForFunction(()=>JSON.parse(window.connectorNodes.planner.widgets.find(w=>w.name==='config').value).optimized['0']?.text==='远程测试优化结果');
    await optimize(characterRoot,'使用当前段抽帧和参考图片优化提示词');
    check(requests.slice(2).every(request=>request.body.connection.kind==='remote'),"远程连接器仍使用远程接口");
    await viggleRoot.getByRole('button',{name:'编辑 / 分段',exact:true}).click();
    const editor=page.locator('.yr-pgs-ov');
    await editor.getByText('视频编辑器',{exact:true}).waitFor();
    await page.waitForFunction(()=>[...document.querySelectorAll('.yr-pgs-ov select option')].some(option=>option.value==='6' && option.textContent.includes('帧')));
    await editor.locator('select').evaluateAll(selects=>{
      const control=selects.find(select=>[...select.options].some(option=>option.value==='6' && option.textContent.includes('帧')));
      if(!control)throw new Error('未找到编辑器重叠帧选择');
      control.value='6';control.dispatchEvent(new Event('change',{bubbles:true}));
    });
    await editor.getByRole('button',{name:'保存',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.vv-controls')?.textContent.includes('分段上下文6 帧'));
    check(await page.evaluate(()=>JSON.parse(window.connectorNodes.planner.widgets.find(w=>w.name==='config').value).plan.overlap)===6,"编辑器保存的 6 帧上下文被保留并展示");
    check(await viggleRoot.getByRole('combobox',{name:'分段上下文',exact:true}).count()===0,"配置器上下文展示值统一由编辑器决定");
    await page.screenshot({path:'F:/ComfyUI/ComfyUI/custom_nodes/ComfyUI-yton-nodes/.artifacts/local-llm-connector.png',fullPage:true});
    check(!errors.length,`浏览器无运行错误：${errors.join(';')}`);
    return {checks,errors};
  } finally {await context.close();}
}
