// Exercise the real editor in an isolated page, without changing workflows or queueing jobs.
async (basePage) => {
  const context = await basePage.context().browser().newContext({viewport:{width:1100,height:800}});
  const page = await context.newPage();
  const checks = [];
  const check = (value, message) => {if (!value) throw new Error(message); checks.push(message);};
  try {
    await page.route("**/yton-prompt-editor-test", route => route.fulfill({contentType:"text/html", body:
      '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>人物替换提示词编辑器</title><style>body{background:#171b20;color:#eef1f7;font:14px sans-serif;padding:30px}main{width:650px}button{margin:12px 0}input{display:block}</style><main><h2>片段提示词</h2><button id="reference">@ 引用</button><div id="host"></div><input aria-label="其他输入框"></main></html>'}));
    await page.goto("http://127.0.0.1:8188/yton-prompt-editor-test");
    await page.evaluate(async () => {
      const {buildRichEditor} = await import(`/extensions/ComfyUI-yton-nodes/js/replacement/prompt_editor.js?test=${Date.now()}`);
      const {injectStyles} = await import("/extensions/ComfyUI-yton-nodes/js/replacement/prompt_editor_support.js");
      injectStyles();
      window.mountEditor = initialText => {
        window.editorAbort?.abort(); window.richEditor?.dispose();
        window.editorAbort = new AbortController(); window.savedPrompt = initialText;
        window.richEditor = buildRichEditor({initialText,resolveLabels:true,signal:window.editorAbort.signal,
          assets:[{kind:"video",alias:"视频",nativeLabel:"<Video 1>"},
            {kind:"image",alias:"图片1",nativeLabel:"<Picture 1>"},
            {kind:"image",alias:"图片2",nativeLabel:"<Picture 2>"}],
          onInput:text => {window.savedPrompt = text;}});
        document.querySelector("#host").replaceChildren(window.richEditor.editor);
      };
      const button = document.querySelector("#reference");
      button.addEventListener("pointerdown", event => event.preventDefault());
      button.addEventListener("click", () => {window.richEditor.focus(); window.richEditor.showAliasMenu();});
      window.placeCaret = (tokenIndex, offset) => {
        const editor = window.richEditor.editor;
        const node = editor.querySelectorAll(".yr-pgs-token")[tokenIndex].nextSibling;
        editor.focus();
        const range = document.createRange(); range.setStart(node, offset); range.collapse(true);
        getSelection().removeAllRanges(); getSelection().addRange(range);
      };
    });
    const initial = "将@视频中的左侧人物替换为@图片1；\n第二行将@视频中的右侧人物替换为，保留原背景。";
    const position = "中的右侧人物替换为".length;
    const selectedText = initial.replace("右侧人物替换为，", "右侧人物替换为@图片2，");
    const settleMenu = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.evaluate(({initial,position}) => {window.mountEditor(initial); window.placeCaret(2,position);}, {initial,position});
    await page.keyboard.type("@");
    await page.locator(".yr-pgs-alias-menu").waitFor();
    await settleMenu();
    check(await page.evaluate(() => document.activeElement === window.richEditor.editor), "@候选列表保持编辑器焦点");
    await page.evaluate(() => {const s=getSelection(); window.openCaret={node:s.anchorNode,offset:s.anchorOffset};});
    for (const key of ["ArrowDown","ArrowDown","ArrowUp","ArrowDown"]) await page.keyboard.press(key);
    check((await page.locator(".yr-pgs-alias-item-active").innerText()).includes("@图片2"), "上下键准确切换候选项");
    check(await page.evaluate(() => {const s=getSelection(); return s.anchorNode===window.openCaret.node && s.anchorOffset===window.openCaret.offset;}), "上下切换候选时光标原地不动");
    await page.keyboard.press("Enter");
    check(await page.evaluate(() => window.savedPrompt) === selectedText, "多行文字和多个chip之后仍在原位置插入引用");
    check(await page.locator(".yr-pgs-alias-menu").count() === 0, "选中后关闭候选列表");
    await page.keyboard.type("继续");
    check(await page.evaluate(() => window.savedPrompt) === selectedText.replace("@图片2，", "@图片2继续，"), "插入后继续输入保持在chip之后");

    await page.evaluate(({initial,position}) => {window.mountEditor(initial); window.placeCaret(2,position);}, {initial,position});
    await page.keyboard.type("@"); await settleMenu();
    await page.keyboard.press("ArrowDown"); await page.keyboard.press("Escape");
    await settleMenu(); await page.keyboard.type("取消");
    check(await page.evaluate(() => window.savedPrompt) === initial.replace("右侧人物替换为，", "右侧人物替换为@取消，"), "Escape关闭候选后继续在原光标处输入");
    check(await page.locator(".yr-pgs-alias-menu").count() === 0, "Escape后候选列表不会延迟重开");

    await page.evaluate(({initial,position}) => {window.mountEditor(initial); window.placeCaret(2,position);}, {initial,position});
    await page.keyboard.type("@"); await settleMenu();
    await page.locator(".yr-pgs-alias-item").filter({hasText:"@图片2"}).click();
    check(await page.evaluate(() => window.savedPrompt) === selectedText, "鼠标选择与键盘选择使用相同的插入位置");
    check(await page.evaluate(() => document.activeElement===window.richEditor.editor), "鼠标选择后焦点返回编辑器");

    await page.evaluate(({initial,position}) => {window.mountEditor(initial); window.placeCaret(2,position);}, {initial,position});
    await page.getByRole("button",{name:"@ 引用",exact:true}).click();
    await settleMenu();
    await page.keyboard.press("ArrowDown"); await page.keyboard.press("ArrowDown"); await page.keyboard.press("Enter");
    check(await page.evaluate(() => window.savedPrompt) === selectedText, "工具栏引用按钮保留chip后的光标位置");

    await page.evaluate(({initial,position}) => {window.mountEditor(initial); window.placeCaret(2,position);}, {initial,position});
    await page.keyboard.type("@"); await settleMenu(); await page.keyboard.press("ArrowLeft");
    check(await page.locator(".yr-pgs-alias-menu").count() === 0, "左右移动光标时退出候选选择");
    await page.keyboard.type("这里");
    check(await page.evaluate(() => window.savedPrompt) === initial.replace("右侧人物替换为，", "右侧人物替换为这里@，"), "退出候选后方向键恢复正常移动光标");

    await page.evaluate(({initial,position}) => {window.mountEditor(initial); window.placeCaret(2,position);}, {initial,position});
    await page.keyboard.type("@"); await settleMenu(); await page.keyboard.press("Tab");
    check(await page.locator(".yr-pgs-alias-menu").count() === 0, "Tab离开输入框时关闭候选列表");
    check(await page.getByLabel("其他输入框").evaluate(element => element===document.activeElement), "Tab正常切换到下一个输入框");

    await page.evaluate(({initial,position}) => {window.mountEditor(initial); window.placeCaret(2,position);}, {initial,position});
    await page.keyboard.press("Enter"); await page.keyboard.type("新行@"); await settleMenu();
    await page.keyboard.press("ArrowDown"); await page.keyboard.press("ArrowDown"); await page.keyboard.press("Enter");
    await page.keyboard.type("后续");
    const multilineText = await page.evaluate(() => window.savedPrompt);
    check(multilineText.includes("右侧人物替换为\n新行@图片2后续，保留原背景。"), `Enter创建新行后引用和后续文字保持原顺序：${JSON.stringify(multilineText)}`);

    async function clipboard(type = "copy") {
      return page.evaluate(type => {
        const data = new DataTransfer();
        const event = new ClipboardEvent(type, {bubbles:true,cancelable:true,clipboardData:data});
        window.richEditor.editor.dispatchEvent(event);
        return {text:data.getData("text/plain"),handled:event.defaultPrevented,prompt:window.savedPrompt};
      }, type);
    }
    const selectAll = () => page.evaluate(() => {
      const editor=window.richEditor.editor;editor.focus();
      const range=document.createRange();range.selectNodeContents(editor);
      getSelection().removeAllRanges();getSelection().addRange(range);
    });
    await selectAll();
    const typedLines=await clipboard();
    check(typedLines.text===multilineText.replaceAll('@视频','<Video 1>').replaceAll('@图片1','<Picture 1>').replaceAll('@图片2','<Picture 2>'),"Enter 创建的段落在复制时保留原换行");
    const singleLine="将@视频中的人物替换为@图片1，保留<Subject 1>的身份与<d>你好</d>。";
    const displayed="将<Video 1>中的人物替换为<Picture 1>，保留<Subject 1>的身份与<d>你好</d>。";
    await page.evaluate(text=>{window.mountEditor(text);window.richEditor.editor.style.width="160px";},singleLine);
    await selectAll();
    let copied=await clipboard();
    check(copied.handled && copied.text===displayed,"复制引用标签与对白按显示文字输出，视觉折行不会变成换行");
    check(copied.prompt===singleLine,"复制不改变提示词保存内容和素材别名");
    const explicitLines="第一行@视频\n\n第二行@图片1\n";
    await page.evaluate(text=>window.mountEditor(text),explicitLines);await selectAll();
    copied=await clipboard();
    check(copied.text==="第一行<Video 1>\n\n第二行<Picture 1>\n","复制保留用户的空行与末尾换行");
    check(await page.evaluate(()=>window.richEditor.getText())===explicitLines,"文本读取保留原始末尾换行");
    await page.evaluate(()=>{
      window.mountEditor("开头@视频中的人物替换为@图片1，结束。");
      const editor=window.richEditor.editor,range=document.createRange();editor.focus();
      range.setStart(editor.firstChild,2);range.setEnd(editor.querySelectorAll('.yr-pgs-token')[1].nextSibling,0);
      getSelection().removeAllRanges();getSelection().addRange(range);
    });
    copied=await clipboard();
    check(copied.text==="<Video 1>中的人物替换为<Picture 1>","局部选择只复制选中的引用和文字");
    const cut=await clipboard("cut");
    check(cut.text===copied.text && cut.prompt==="开头，结束。","剪切使用相同复制规则，并同步保存删除后的提示词");
    await page.evaluate(()=>{window.mountEditor("只读@图片1");window.richEditor.editor.contentEditable="false";});await selectAll();
    const readonly=await clipboard("cut");
    check(readonly.text==="只读<Picture 1>" && readonly.prompt==="只读@图片1","只读提示词可复制，剪切不会删除文字");
    await page.screenshot({path:"C:/Users/YuanTong/AppData/Local/Temp/replacement-prompt-editor-fixed.png"});
    return {checks};
  } finally {await context.close();}
}
