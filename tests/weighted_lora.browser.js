// Run against an isolated ComfyUI browser context with the new schema injected.
export async function runWeightedLora(page, definition, baseURL = "http://127.0.0.1:8188") {
  const context = await page.context().browser().newContext({ viewport: { width: 1500, height: 950 } });
  const p = await context.newPage();
  const errors = [];
  p.on("pageerror", error => errors.push(error.message));
  await context.route(/\/(?:api\/)?object_info(?:\/[^?]+)?(?:\?.*)?$/, async route => {
    const response = await route.fetch();
    const data = await response.json();
    data[definition.name] = definition;
    await route.fulfill({ response, json: data });
  });
  await context.route("**/userdata/**", route => route.request().method() === "GET" ? route.continue() : route.fulfill({ json: {} }));
  await context.route(/\/(?:api\/)?settings(?:\/|$)/, route => route.request().method() === "POST" ? route.fulfill({ json: {} }) : route.continue());
  await context.route(/\/(?:api\/)?prompt$/, route => route.request().method() === "POST" ? route.abort() : route.continue());
  try {
    await p.goto(baseURL);
    await p.getByTestId("workflows-tab-button").waitFor({ timeout: 60000 });
    await p.waitForFunction(() => window.LiteGraph?.registered_node_types.YtonWeightedLoraLoader);
    const result = await p.evaluate(async definition => {
      const assert = (value, message) => { if (!value) throw Error(message); };
      const app = window.comfyAPI.app.app;
      app.graph.clear();
      let node = LiteGraph.createNode(definition.name);
      app.graph.add(node);
      node.pos = [430, 180];
      assert(typeof node.ytonAddLora === "function", "LoRA extension is installed");
      const loras = definition.input.required.loras[1].yton_loras;
      for (let i = 0; i < 4; i++) node.ytonAddLora(loras[i]);
      const number = LiteGraph.createNode("PrimitiveFloat");
      app.graph.add(number); number.pos = [50, 160];
      number.widgets[0].value = 0.45;
      number.connect(0, node, node.findInputSlot("strengths.strength_2"));
      const id = node.id;
      const draw = async () => {
        app.canvas.ds.scale = 1.1; app.canvas.ds.offset = [0, 0];
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        app.canvas.draw(true, true);
      };
      await draw();
      const input = node.inputs.find(i => i.name === "strengths.strength_2");
      const widget = node.widgets.find(w => w.name === "lora_row_2");
      const inputY = node.getInputPos(node.findInputSlot(input.name))[1] - node.pos[1];
      assert(Math.abs(inputY - (widget.y + 15)) < 20, "socket is beside its LoRA row");
      assert(!widget.disabled && !widget.connectionSuppressed, "linked row still displays its controls");
      const prompt = async () => (await app.graphToPrompt()).output[id].inputs;
      assert(Array.isArray((await prompt())["strengths.strength_2"]), "wired strength is exported");
      node.ytonRemoveLora(1);
      assert(node.inputs.find(i => i.name === "strengths.strength_2").link != null, "removing an earlier row preserves the correct wire");
      const added = node.ytonAddLora(loras[5]);
      assert(added.slot === 1, "a removed slot is reused without moving other rows");
      const saved = app.graph.serialize();
      await app.loadGraphData(saved);
      node = app.graph.getNodeById(id);
      await draw();
      const restored = await prompt();
      assert(JSON.parse(restored.loras).map(r => r.slot).join() === "0,2,3,1", "row order survives reload");
      assert(Array.isArray(restored["strengths.strength_2"]), "wire survives reload");
      node.disconnectInput(node.findInputSlot("strengths.strength_2"));
      await draw();
      assert(node.inputs.some(i => i.name === "strengths.strength_2"), "disconnecting keeps the row socket");
      assert(!("strengths.strength_2" in await prompt()), "disconnected input falls back to inline strength");
      const rows = JSON.parse(node.widgets.find(w => w.name === "loras").value);
      assert(rows.find(r => r.slot === 2).strength === 1, "inline strength remains stored");
      return { title: node.title, inputs: node.inputs.map(i => i.name), size: [...node.size], checks: "add/delete, aligned sockets, wires, API export, save/reload, disconnect" };
    }, definition);
    const point = async (kind, slot = 0) => p.evaluate(({ kind, slot }) => {
      const app = window.comfyAPI.app.app;
      const node = app.graph._nodes.find(n => n.comfyClass === "YtonWeightedLoraLoader");
      const widget = node.widgets.find(w => w.name === (kind === "add" ? "＋ 添加 LoRA" : `lora_row_${slot}`));
      let pos;
      if (kind === "output") {
        const source = app.graph._nodes.find(n => n.comfyClass === "PrimitiveFloat");
        pos = source.getConnectionPos(false, 0, new Float32Array(2));
      } else if (kind === "input") pos = node.getInputPos(node.findInputSlot(`strengths.strength_${slot}`));
      else pos = [node.pos[0] + (kind === "add" || kind === "menu" ? node.size[0] / 2 : kind === "toggle" ? 30 : kind === "choose" ? 90 : node.size[0] - 46), node.pos[1] + widget.y + 15];
      const rect = app.canvas.canvas.getBoundingClientRect();
      return { x: (pos[0] + app.canvas.ds.offset[0]) * app.canvas.ds.scale + rect.x,
        y: (pos[1] + app.canvas.ds.offset[1]) * app.canvas.ds.scale + rect.y };
    }, { kind, slot });
    let pos = await point("add");
    await p.mouse.click(pos.x, pos.y);
    const names = definition.input.required.loras[1].yton_loras;
    const filter = p.getByRole("textbox", { name: "搜索 LoRA", exact: true });
    await filter.fill("yton-search-no-matching-lora");
    if (await p.locator(".litecontextmenu .litemenu-entry:visible").count()) throw Error("unmatched search should hide all LoRAs");
    await filter.fill("");
    if (await p.locator(".litecontextmenu .litemenu-entry:visible").count() !== names.length) throw Error("clearing search should restore the complete list");
    await filter.fill(names[6].toUpperCase());
    const visible = await p.locator(".litecontextmenu .litemenu-entry:visible").allTextContents();
    if (visible.length !== 1 || visible[0].trim() !== names[6]) throw Error("search should match the full path without case sensitivity");
    await filter.press("Enter");
    pos = await point("choose", 4);
    await p.mouse.click(pos.x, pos.y);
    await filter.fill(names[7]);
    await p.getByText(names[7], { exact: true }).last().click();
    await p.evaluate(name => {
      const node = window.comfyAPI.app.app.graph._nodes.find(n => n.comfyClass === "YtonWeightedLoraLoader");
      const row = JSON.parse(node.widgets.find(w => w.name === "loras").value).find(r => r.slot === 4);
      if (row.lora !== name) throw Error("filtered selection should update the existing row");
    }, names[7]);
    pos = await point("increase");
    await p.mouse.click(pos.x, pos.y);
    pos = await point("toggle", 3);
    await p.mouse.click(pos.x, pos.y);
    const from = await point("output"), to = await point("input", 2);
    await p.mouse.move(from.x, from.y); await p.mouse.down();
    await p.mouse.move(to.x, to.y, { steps: 12 }); await p.mouse.up();
    const ui = await p.evaluate(() => {
      const app = window.comfyAPI.app.app;
      const node = app.graph._nodes.find(n => n.comfyClass === "YtonWeightedLoraLoader");
      const rows = JSON.parse(node.widgets.find(w => w.name === "loras").value);
      if (rows.length !== 5 || rows[0].strength !== 1.05 || rows.find(r => r.slot === 3).enabled) throw Error("mouse row controls did not update: " + JSON.stringify(rows));
      if (node.inputs.find(i => i.name === "strengths.strength_2").link == null) throw Error("cannot drag a real wire to the row strength socket");
      return "mouse: add menu, strength arrow, toggle, drag strength wire";
    });
    const originalLink = await p.evaluate(() => {
      const node = window.comfyAPI.app.app.graph._nodes.find(n => n.comfyClass === "YtonWeightedLoraLoader");
      return node.inputs.find(i => i.name === "strengths.strength_2").link;
    });
    for (const [command, expected] of [["置顶", "2,0,3,1,4"], ["下移", "0,2,3,1,4"], ["置底", "0,3,1,4,2"], ["上移", "0,3,1,2,4"]]) {
      const position = await point("menu", 2);
      await p.mouse.click(position.x, position.y, { button: "right" });
      const menu = await p.locator(".litecontextmenu .litemenu-entry").allTextContents();
      if (menu.map(text => text.trim()).join() !== "上移,下移,置顶,置底") throw Error("row context menu should only contain the four reorder commands: " + JSON.stringify(menu));
      await p.getByText(command, { exact: true }).last().click();
      await p.evaluate(async ({ expected, originalLink }) => {
        const app = window.comfyAPI.app.app;
        const node = app.graph._nodes.find(n => n.comfyClass === "YtonWeightedLoraLoader");
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        app.canvas.draw(true, true);
        const rows = JSON.parse(node.widgets.find(w => w.name === "loras").value);
        if (rows.map(row => row.slot).join() !== expected) throw Error(`context menu order: expected ${expected}, got ${rows.map(row => row.slot).join()}`);
        const widgets = node.widgets.filter(w => w.type === "yton_lora_row");
        if (widgets.map(w => w.value.slot).join() !== expected) throw Error("visible row order differs from loading order");
        if (node.inputs.find(i => i.name === "strengths.strength_2").link !== originalLink) throw Error("reordering changed the strength wire");
        const moved = widgets.find(w => w.value.slot === 2);
        const inputY = node.getInputPos(node.findInputSlot("strengths.strength_2"))[1] - node.pos[1];
        if (Math.abs(inputY - (moved.y + 15)) >= 20) throw Error("strength socket did not follow the moved row");
        if (rows.find(row => row.slot === 2).strength !== 1 || !rows.find(row => row.slot === 2).enabled) throw Error("right click changed the LoRA settings");
      }, { expected, originalLink });
    }
    await p.evaluate(async originalLink => {
      const app = window.comfyAPI.app.app;
      const before = app.graph._nodes.find(n => n.comfyClass === "YtonWeightedLoraLoader");
      const saved = app.graph.serialize();
      await app.loadGraphData(saved);
      const node = app.graph.getNodeById(before.id);
      const inputs = (await app.graphToPrompt()).output[node.id].inputs;
      if (JSON.parse(inputs.loras).map(row => row.slot).join() !== "0,3,1,2,4") throw Error("reordered stack changed after reload");
      if (node.inputs.find(i => i.name === "strengths.strength_2").link !== originalLink || !Array.isArray(inputs["strengths.strength_2"])) throw Error("reordered strength wire was not preserved in workflow and API export");
    }, originalLink);
    if (errors.length) throw Error(errors.join("\n"));
    return { ...result, ui, search: "case-insensitive paths, no matches, clear, Enter selection, replace existing row", reorder: "right click: top/down/bottom/up, aligned sockets, stable strength wire, save/reload" };
  } finally {
    await context.close();
  }
}
