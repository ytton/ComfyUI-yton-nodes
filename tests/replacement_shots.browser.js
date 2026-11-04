// Run tests/replacement_preview_server.py first. All media and APIs use temporary fixtures.
async (basePage) => {
  const context = await basePage.context().browser().newContext({viewport:{width:1440,height:1000}});
  const page = await context.newPage();
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.route('**/yton-shot-editor-test', route => route.fulfill({contentType:'text/html',
      body:'<!doctype html><html><head><title>分镜切分测试</title></head><body></body></html>'}));
    await page.route('**/scripts/api.js', route => route.fulfill({contentType:'text/javascript',
      body:'export const api = {fetchApi:(path,options)=>fetch(path,options)};'}));
    for (const pattern of ['**/yton/replacement/**', '**/view?**']) {
      await page.route(pattern, async route => {
        const url = new URL(route.request().url());
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
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 4);
    const boundaries = await dialog.locator('.yr-pgs-seg-item').evaluateAll(items => items.map(item => {
      const match = item.title.match(/帧 (\d+) ~ (\d+)/);
      return [Number(match[1]), Number(match[2])];
    }));
    check(JSON.stringify(boundaries) === JSON.stringify([[0,36],[36,84],[84,123],[118,156]]), 'camera cuts and overlap preserved');
    check(await dialog.locator('.yr-pgs-seg-item').nth(1).getAttribute('title').then(value => value.includes('新镜头')), 'cut is marked in the editor');
    check(await save.isEnabled(), 'save enabled after detection');
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
    const length = dialog.locator('select').filter({has:page.locator('option[value="7.2917"]')});
    await length.selectOption('7.2917');
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 3);
    await save.click();
    await dialog.waitFor({state:'detached'});
    check((await page.evaluate(() => window.shotConfig.plan.frames)) === 175, 'H3 limit longer than source remains legal');
    await page.evaluate(() => window.openShotTest());
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 3);
    await dialog.getByLabel('切分方式', {exact:true}).selectOption('fixed');
    await page.waitForFunction(() => document.querySelectorAll('.yr-pgs-seg-item').length === 1);
    await dialog.getByRole('button', {name:'取消', exact:true}).click();
    check((await page.evaluate(() => window.shotConfig.plan.split)) === 'shots', 'cancel preserves saved shot plan');
    check(errors.length === 0, errors.join('\n'));
    return {checks:['actual cuts','overlap within length cap','serialized plan','preview equals execution',
      'reopen','H3 limit longer than source','fixed mode','cancel'], boundaries};
  } finally { await context.close(); }
}
