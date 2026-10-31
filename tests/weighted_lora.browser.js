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
      else pos = [node.pos[0] + (kind === "add" ? node.size[0] / 2 : kind === "toggle" ? 30 : node.size[0] - 46), node.pos[1] + widget.y + 15];
      const rect = app.canvas.canvas.getBoundingClientRect();
      return { x: (pos[0] + app.canvas.ds.offset[0]) * app.canvas.ds.scale + rect.x,
        y: (pos[1] + app.canvas.ds.offset[1]) * app.canvas.ds.scale + rect.y };
    }, { kind, slot });
    let pos = await point("add");
    await p.mouse.click(pos.x, pos.y);
    await p.getByText(definition.input.required.loras[1].yton_loras[6], { exact: true }).last().click();
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
    if (errors.length) throw Error(errors.join("\n"));
    return { ...result, ui };
  } finally {
    await context.close();
  }
}
