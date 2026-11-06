// Run tests/replacement_preview_server.py first. All media and APIs use temporary fixtures.
async (basePage) => {
  const context = await basePage.context().browser().newContext({viewport:{width:1440,height:1000}});
  const page = await context.newPage();
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const errors = [], detections = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.route('**/yton-shot-editor-test', route => route.fulfill({contentType:'text/html',
      body:'<!doctype html><html><head><title>分镜切分测试</title></head><body></body></html>'}));
    await page.route('**/scripts/api.js', route => route.fulfill({contentType:'text/javascript',
      body:'export const api = {fetchApi:(path,options)=>fetch(path,options)};'}));
    for (const pattern of ['**/yton/replacement/**', '**/view?**']) {
      await page.route(pattern, async route => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/shot-plan')) detections.push(route.request().postDataJSON());
        const response = await route.fetch({url:'http://127.0.0.1:8190' + url.pathname.replace(/^\/api/, '') + url.search});
        await route.fulfill({response});
      });
    }
    const config = await (await page.request.get('http://127.0.0.1:8190/shot-config')).json();
    await page.goto('http://127.0.0.1:8188/yton-shot-editor-test');
    await page.evaluate(async config => {
      const {openReplacementEditor} = await import('/extensions/ComfyUI-yton-nodes/js/replacement_editor.js');
      window.shotConfig = config;
      window.openShotTest = () => openReplacementEditor(window.shotConfig, result => { window.shotConfig = result; });
      await window.openShotTest();
    }, config);
    const dialog = page.locator('.yr-pgs-ov');
    const save = dialog.getByRole('button', {name:'保存', exact:true});
    await dialog.locator('.yr-pgs-seg-item').first().waitFor();
    await dialog.getByLabel('切分方式', {exact:true}).selectOption('shots');
    await dialog.getByText('点击“检测镜头”分析原视频。', {exact:true}).waitFor();
    check(detections.length === 0 && await save.isDisabled(), 'switching to shots waits for an explicit detection');
    await dialog.getByRole('button', {name:'检测镜头', exact:true}).click();
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 4);
    const boundaries = await dialog.locator('.yr-pgs-seg-item').evaluateAll(items => items.map(item => {
      const match = item.title.match(/帧 (\d+) ~ (\d+)/);
      return [Number(match[1]), Number(match[2])];
    }));
    check(JSON.stringify(boundaries) === JSON.stringify([[0,36],[36,84],[84,123],[118,156]]), 'camera cuts and overlap preserved');
    check(await dialog.locator('.yr-pgs-seg-item').nth(1).getAttribute('title').then(value => value.includes('新镜头')), 'cut is marked in the editor');
    check(await save.isEnabled(), 'save enabled after detection');
    check(detections.length === 1, 'only the detection button analyses the video');
    await save.click();
    await dialog.waitFor({state:'detached'});
    const saved = await page.evaluate(() => window.shotConfig);
    check(saved.plan.split === 'shots' && JSON.stringify(saved.plan.cuts) === '[36,84]', 'detected boundaries serialized');
    const result = await (await page.request.post('http://127.0.0.1:8190/yton/replacement/plan', {data:saved})).json();
    check(JSON.stringify(result.plan.segments.map(segment => [segment.start,segment.end])) === JSON.stringify(boundaries), 'execution uses the exact preview boundaries');
    await page.evaluate(() => window.openShotTest());
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 4);
    check(await dialog.getByLabel('切分方式', {exact:true}).inputValue() === 'shots', 'reopening retains camera-cut mode');
    check(await dialog.getByLabel('灵敏度', {exact:true}).inputValue() === '0.8', 'reopening retains sensitivity');
    check(detections.length === 1, 'reopening reuses saved cuts');
    const track = dialog.locator('.yr-pgs-ts');
    const dragBoundary = async (index, frame) => {
      const handle = dialog.getByRole('button', {name:`调整第 ${index + 1}、${index + 2} 段分界`, exact:true});
      await handle.scrollIntoViewIfNeeded();
      const box = await handle.boundingBox(), timeline = await track.boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(timeline.x + timeline.width * frame / 156, box.y + box.height / 2, {steps:6});
      await page.mouse.up();
    };
    const readSegments = () => dialog.locator('.yr-pgs-seg-item').evaluateAll(items => items.map(item => {
      const match = item.title.match(/帧 (\d+) ~ (\d+)/);return [Number(match[1]),Number(match[2])];
    }));
    await dragBoundary(0, 42);
    const adjusted = await readSegments();
    check(JSON.stringify(adjusted) === JSON.stringify([[0,42],[42,84],[84,123],[118,156]]), 'dragging resizes both adjacent shots');
    await dragBoundary(1, 122);
    const constrained = await readSegments();
    check(JSON.stringify(constrained) === JSON.stringify([[0,42],[42,117],[117,123],[118,156]]), 'drag cannot cross the next segment with context');
    const constrainedPlan = await (await page.request.post('http://127.0.0.1:8190/yton/replacement/plan', {
      data:{...saved,plan:{...saved.plan,manual_segments:constrained.map(([start,end])=>({start,end}))}},
    })).json();
    check(JSON.stringify(constrainedPlan.plan.segments.map(s=>[s.start,s.end])) === JSON.stringify(constrained), 'clamped shot boundaries remain executable');
    await dragBoundary(1, 84);
    check(detections.length === 1, 'dragging does not trigger detection');
    await save.click();await dialog.waitFor({state:'detached'});
    const manual = await page.evaluate(() => window.shotConfig);
    const actual = await (await page.request.post('http://127.0.0.1:8190/yton/replacement/plan', {data:manual})).json();
    check(JSON.stringify(actual.plan.segments.map(segment => [segment.start,segment.end])) === JSON.stringify(adjusted), 'execution retains manually adjusted boundaries');
    await page.evaluate(() => window.openShotTest());
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 4);
    check(JSON.stringify(await readSegments()) === JSON.stringify(adjusted), 'reopening retains manual lengths');
    const length = dialog.locator('select').filter({has:page.locator('option[value="7.2917"]')});
    await length.selectOption('7.2917');
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 3);
    check(detections.length === 1, 'changing maximum length recalculates without detecting');
    await save.click();
    await dialog.waitFor({state:'detached'});
    check((await page.evaluate(() => window.shotConfig.plan.frames)) === 175, 'H3 limit longer than source remains legal');
    await page.evaluate(() => window.openShotTest());
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 3);
    await dialog.getByLabel('切分方式', {exact:true}).selectOption('fixed');
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 1);
    await dialog.getByRole('button', {name:'取消', exact:true}).click();
    check((await page.evaluate(() => window.shotConfig.plan.split)) === 'shots', 'cancel preserves saved shot plan');
    await page.evaluate(() => window.openShotTest());
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 3);
    await dialog.getByLabel('切分方式', {exact:true}).selectOption('fixed');
    const length2 = dialog.locator('select').filter({has:page.locator('option[value="2.3333"]')});
    await length2.selectOption('2.3333');
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 3);
    await dragBoundary(0, 48);
    check(JSON.stringify(await readSegments()) === JSON.stringify([[0,48],[43,107],[102,156]]), 'fixed-mode drag preserves five context frames and changes lengths');
    await save.click();await dialog.waitFor({state:'detached'});
    const fixed = await page.evaluate(() => window.shotConfig);
    const fixedPlan = await (await page.request.post('http://127.0.0.1:8190/yton/replacement/plan', {data:fixed})).json();
    check(JSON.stringify(fixedPlan.plan.segments.map(s=>[s.start,s.end])) === '[[0,48],[43,107],[102,156]]', 'fixed manual execution matches preview');
    await page.evaluate(() => window.openShotTest());
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 3);
    await dragBoundary(0, 1);
    check((await readSegments())[0][1] === 6, 'drag clamps to a valid boundary and keeps overlap');
    await dialog.getByRole('button', {name:'取消', exact:true}).click();
    check((await page.evaluate(() => window.shotConfig.plan.manual_segments[0].end)) === 48, 'cancel discards resized lengths');
    await page.evaluate(() => window.openShotTest());
    await dialog.getByLabel('切分方式', {exact:true}).selectOption('shots');
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 4);
    await dialog.getByLabel('灵敏度', {exact:true}).fill('0.6');
    await dialog.getByLabel('灵敏度', {exact:true}).press('Tab');
    await dialog.getByText('点击“检测镜头”分析原视频。', {exact:true}).waitFor();
    check(detections.length === 1 && await save.isDisabled(), 'changing detection parameters waits for the button');
    await dialog.getByRole('button', {name:'检测镜头',exact:true}).click();
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 4);
    check(detections.length === 2, 'explicit redetection runs once');
    await page.screenshot({path:'F:/ComfyUI/ComfyUI/custom_nodes/ComfyUI-yton-nodes/.artifacts/replacement-shots.png',fullPage:true});
    check(errors.length === 0, errors.join('\n'));
    return {checks:['actual cuts','overlap within length cap','serialized plan','preview equals execution',
      'explicit detection only','saved cuts reused','drag shot boundaries','drag fixed boundaries with context','preview equals manual execution',
      'reopen manual lengths','boundary constraints','H3 limit longer than source','fixed mode','cancel'], boundaries};
  } finally { await context.close(); }
}
