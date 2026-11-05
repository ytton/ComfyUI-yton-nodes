async (basePage) => {
  const context = await basePage.context().browser().newContext({ viewport: { width: 1200, height: 800 } });
  const page = await context.newPage();
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  try {
    for (const pattern of ["**/userdata/**", "**/settings/**"])
      await page.route(pattern, route => ["POST", "PUT", "DELETE"].includes(route.request().method()) ? route.fulfill({ json: {} }) : route.continue());
    await page.route(/\/(?:api\/)?settings$/, async route => {
      if (route.request().method() !== "GET") return route.fulfill({ json: {} });
      const response = await route.fetch();
      await route.fulfill({ json: { ...await response.json(), "Comfy.Workflow.Persist": false, "Comfy.Workflow.AutoSave": "off", "Comfy.VueNodes.Enabled": false } });
    });
    await page.route("**/prompt", route => route.request().method() === "POST" ? route.abort() : route.continue());
    await page.goto("http://127.0.0.1:8188/");
    await page.waitForFunction(() => {
      const app = window.comfyAPI?.app?.app;
      if (!app?.vueAppReady || !app.graphLoadSequence || app.committedGraphLoadSequence !== app.graphLoadSequence || app.pendingGraphLoads.size || !window.LiteGraph?.registered_node_types?.YtonInputSwitch) return false;
      if (window.inputSwitchSequence !== app.graphLoadSequence) {
        window.inputSwitchSequence = app.graphLoadSequence; window.inputSwitchReady = performance.now();
      }
      return performance.now() - window.inputSwitchReady > 1000;
    }, {}, { timeout: 60000 });
    const created = await page.evaluate(async () => {
      const app = window.comfyAPI.app.app;
      await app.loadGraphData({ version: 0.4, nodes: [], links: [], groups: [], config: {}, extra: {} });
      const node = LiteGraph.createNode("YtonInputSwitch");
      const control = LiteGraph.createNode("PrimitiveBoolean");
      const source = LiteGraph.createNode("PrimitiveString");
      app.graph.add(node); app.graph.add(control); app.graph.add(source);
      node.pos = [400, 100]; control.pos = [50, 100]; source.pos = [50, 300];
      app.canvas.ds.scale = 1; app.canvas.ds.offset = [0, 0];
      source.widgets.find(widget => widget.name === "value").value = "测试输入";
      source.connect(0, node, node.inputs.findIndex(slot => slot.name === "value"));
      window.switchTest = { node, control };
      return node.inputs.map(slot => ({ name: slot.name, type: slot.type, label: slot.label }));
    });
    check(created.length === 2 && created[1].name === "enabled" && created[1].type === "BOOLEAN" && created[1].label === "控制开关", "visible Boolean control socket");
    const panel = page.locator(".yton-input-switch");
    const on = panel.getByRole("button", { name: "开启", exact: true });
    const off = panel.getByRole("button", { name: "关闭", exact: true });
    await off.click();
    check(await off.getAttribute("aria-pressed") === "true", "manual off");
    const manual = await page.evaluate(async () => (await window.comfyAPI.app.app.graphToPrompt()).output[String(window.switchTest.node.id)].inputs);
    check(manual.enabled === false, "manual setting submitted");
    await on.click();
    await page.evaluate(() => {
      const { node, control } = window.switchTest;
      control.widgets.find(widget => widget.name === "value").value = false;
      control.connect(0, node, node.inputs.findIndex(slot => slot.name === "enabled"));
    });
    check(await on.isDisabled() && await off.isDisabled(), "wired control disables manual buttons");
    check(await on.getAttribute("aria-pressed") === "false", "manual state not presented as external result");
    const connected = await page.evaluate(async () => {
      const { node, control } = window.switchTest;
      const { output } = await window.comfyAPI.app.app.graphToPrompt();
      return { input: output[String(node.id)].inputs.enabled, source: String(control.id), value: output[String(control.id)].inputs.value };
    });
    check(connected.input[0] === connected.source && connected.input[1] === 0 && connected.value === false, "external Boolean link submitted");
    const saved = await page.evaluate(() => window.comfyAPI.app.app.graph.serialize());
    await page.evaluate(async saved => {
      const app = window.comfyAPI.app.app;
      await app.loadGraphData(saved);
      window.switchTest.node = app.graph._nodes.find(node => node.type === "YtonInputSwitch");
      window.switchTest.control = app.graph._nodes.find(node => node.type === "PrimitiveBoolean");
    }, saved);
    const restored = await page.evaluate(async () => {
      const { node, control } = window.switchTest;
      const { output } = await window.comfyAPI.app.app.graphToPrompt();
      return { inputs: node.inputs.map(slot => ({ name: slot.name, label: slot.label })), link: output[String(node.id)].inputs.enabled, source: String(control.id) };
    });
    check(restored.inputs.length === 2 && restored.inputs[1].label === "控制开关" && restored.link[0] === restored.source, "save and reload preserve socket and link");
    check(await on.isDisabled() && await off.isDisabled(), "reloaded connected state");
    await page.evaluate(() => {
      const node = window.switchTest.node;
      node.disconnectInput(node.inputs.findIndex(slot => slot.name === "enabled"));
    });
    check(await on.isEnabled() && await off.isEnabled(), "disconnect restores manual control");
    await off.click();
    const disconnected = await page.evaluate(async () => (await window.comfyAPI.app.app.graphToPrompt()).output[String(window.switchTest.node.id)].inputs);
    check(disconnected.enabled === false, "disconnected switch submits manual value");
    return { checks: ["Boolean control socket", "manual toggle", "external link submission", "connected state", "save/reload", "disconnect and manual control"] };
  } finally { await context.close(); }
}
