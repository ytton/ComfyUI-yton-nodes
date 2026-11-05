// Run in an isolated context; object_info injection avoids restarting ComfyUI.
export async function runModeParameters(page, definition, baseURL = "http://127.0.0.1:8188") {
  const context = await page.context().browser().newContext({ viewport: { width: 1440, height: 960 } });
  const p = await context.newPage();
  const errors = [];
  p.on("pageerror", error => errors.push(error.message));
  await context.route(/\/(?:api\/)?object_info(?:\/[^?]+)?(?:\?.*)?$/, async route => {
    const response = await route.fetch();
    const json = await response.json();
    json[definition.name] = definition;
    await route.fulfill({ response, json });
  });
  await context.route("**/userdata/**", route => route.request().method() === "GET" ? route.continue() : route.fulfill({ json: {} }));
  await context.route(/\/(?:api\/)?settings(?:\/|$)/, route => route.request().method() === "POST" ? route.fulfill({ json: {} }) : route.continue());
  try {
    await p.goto(baseURL);
    await p.getByTestId("workflows-tab-button").waitFor({ timeout: 60000 });
    await p.waitForFunction(() => window.LiteGraph?.registered_node_types.YtonModeParameters, { timeout: 60000 });
    await p.evaluate(() => {
      const app = window.comfyAPI.app.app;
      app.graph.clear();
      const node = LiteGraph.createNode("YtonModeParameters");
      app.graph.add(node);
      node.pos = [300, 160];
      app.canvas.ds.offset = [0, 0];
      app.canvas.ds.scale = 1;
      window.modeTestId = node.id;
      if (!node.ytonModeParameters) throw Error("mode extension not installed: " + Object.keys(node));
    });
    const gear = p.getByRole("button", { name: "模式配置", exact: true });
    await gear.click();
    const dialog = p.getByRole("dialog");
    await dialog.getByRole("textbox", { name: "Option 1 名称", exact: true }).fill("普通");
    await dialog.getByRole("textbox", { name: "Option 2 名称", exact: true }).fill("人物替换");
    await dialog.getByRole("button", { name: "＋ 添加 Option", exact: true }).click();
    await dialog.getByRole("textbox", { name: "Option 3 名称", exact: true }).fill("风格");
    await dialog.getByRole("button", { name: "下一步", exact: true }).click();
    const fields = [["LoRA强度", "FLOAT"], ["系统提示词", "STRING"], ["启用遮罩", "BOOLEAN"], ["启用上下文", "BOOLEAN"]];
    for (const [index, [label, type]] of fields.entries()) {
      await dialog.getByRole("button", { name: "＋ 添加输出", exact: true }).click();
      await dialog.getByRole("textbox", { name: `输出 ${index + 1} 名称`, exact: true }).fill(label);
      await dialog.getByRole("combobox", { name: `输出 ${index + 1} 类型`, exact: true }).selectOption(type);
    }
    await dialog.getByRole("button", { name: "下一步", exact: true }).click();
    for (const [label, strength, prompt, mask, history] of [
      ["普通", "0", "普通提示词", false, false],
      ["人物替换", "0.9", "将参考人物替换到原图中\n保留原图的姿势与光影。", true, false],
      ["风格", "0.5", "使用参考画风", false, true],
    ]) {
      await dialog.getByRole("button", { name: label, exact: true }).click();
      await dialog.getByRole("spinbutton", { name: "LoRA强度", exact: true }).fill(strength);
      await dialog.getByRole("textbox", { name: "系统提示词", exact: true }).fill(prompt);
      await dialog.getByRole("checkbox", { name: "启用遮罩", exact: true }).setChecked(mask);
      await dialog.getByRole("checkbox", { name: "启用上下文", exact: true }).setChecked(history);
    }
    await p.screenshot({ path: "F:/ComfyUI/ComfyUI/custom_nodes/ComfyUI-yton-nodes/temp/mode-parameters-settings.png" });
    await dialog.getByRole("button", { name: "保存配置", exact: true }).click();
    await p.getByRole("group", { name: "模式", exact: true }).getByRole("button", { name: "人物替换", exact: true }).click();
    const result = await p.evaluate(async () => {
      const assert = (value, message) => { if (!value) throw Error(message); };
      const app = window.comfyAPI.app.app;
      let node = app.graph.getNodeById(window.modeTestId);
      const config = node.ytonModeParameters.getConfig();
      assert(config.options.length === 3 && config.outputs.length === 4, "configuration saved");
      assert(config.values[config.options[1].id][config.outputs[0].id] === 0.9, "typed float saved");
      assert(config.values[config.options[1].id][config.outputs[2].id] === true, "typed boolean saved");
      assert(node.outputs.map(o => o.type).join() === "STRING,INT,FLOAT,STRING,BOOLEAN,BOOLEAN", "concrete output types");
      assert(node.outputs.map(o => o.name).join() === "模式,索引,LoRA强度,系统提示词,启用遮罩,启用上下文", "configured output names");
      const text = LiteGraph.createNode("StringContains");
      app.graph.add(text);
      node.connect(3, text, text.findInputSlot("string"));
      assert(text.inputs.find(i => i.name === "string").link != null, "real typed output connection");
      const targetId = text.id;
      const saved = app.graph.serialize();
      await app.loadGraphData(saved);
      node = app.graph.getNodeById(window.modeTestId);
      assert(node.outputs.length === 6 && node.outputs[3].type === "STRING", "outputs restored");
      assert(node.widgets.find(w => w.name === "selected").value === config.options[1].id, "selected mode restored");
      let api = (await app.graphToPrompt()).output;
      assert(api[targetId].inputs.string?.[1] === 3, "wire restored at its configured slot: " + JSON.stringify({ target: api[targetId], slots: node.outputs, saved: saved.nodes.map(n => ({ id: n.id, outputs: n.outputs })) }));
      const next = node.ytonModeParameters.getConfig();
      next.outputs.reverse();
      next.options.reverse();
      node.ytonModeParameters.configure(next);
      api = (await app.graphToPrompt()).output;
      assert(api[targetId].inputs.string[1] === 4, "reorder follows field identity: " + JSON.stringify({ target: api[targetId], links: Object.values(app.graph.links), outputs: node.outputs, config: next }));
      const removed = next.outputs.splice(0, 1)[0];
      for (const row of Object.values(next.values)) delete row[removed.id];
      node.ytonModeParameters.configure(next);
      api = (await app.graphToPrompt()).output;
      assert(api[targetId].inputs.string[1] === 3, "delete earlier field preserves later wire");
      next.outputs.find(f => f.label === "系统提示词").type = "INT";
      for (const row of Object.values(next.values)) {
        const promptId = next.outputs.find(f => f.label === "系统提示词").id;
        row[promptId] = 7;
      }
      node.ytonModeParameters.configure(next);
      assert(app.graph.getNodeById(targetId).inputs.find(i => i.name === "string").link == null, "type change disconnects incompatible wire");
      node.ytonModeParameters.configure(config);
      app.graph.remove(app.graph.getNodeById(targetId));
      return { nodeId: node.id, config, prompt: (await app.graphToPrompt()).output[node.id], size: [...node.size] };
    });
    await gear.click();
    await dialog.getByRole("textbox", { name: "Option 1 名称", exact: true }).fill("取消后不应保存");
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
    if (await p.getByRole("button", { name: "取消后不应保存", exact: true }).count()) throw Error("cancel should discard edits");
    await gear.click();
    await dialog.getByRole("textbox", { name: "Option 1 名称", exact: true }).fill("人物替换");
    await dialog.getByRole("button", { name: "3  参数值", exact: true }).click();
    await dialog.getByRole("button", { name: "保存配置", exact: true }).click();
    if (!(await dialog.getByRole("alert").textContent()).includes("重复")) throw Error("duplicate modes must be rejected");
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
    await p.screenshot({ path: "F:/ComfyUI/ComfyUI/custom_nodes/ComfyUI-yton-nodes/temp/mode-parameters-node.png" });
    const relevantErrors = errors.filter(e => /mode_parameters|ModeParameters/.test(e));
    if (relevantErrors.length) throw Error(relevantErrors.join("\n"));
    return { ...result, checks: "gear, option/output/value editor, segmented selection, typed ports, export, reload, reorder/delete wire identity, type changes, cancel, duplicate validation", errors: relevantErrors };
  } catch (error) {
    throw Error(error.message + "\nPage errors: " + errors.join("\n"));
  } finally {
    await context.close();
  }
}
