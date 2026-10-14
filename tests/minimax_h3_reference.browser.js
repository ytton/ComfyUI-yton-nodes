async (page) => {
  const context = await page.context().browser().newContext({ viewport: { width: 1440, height: 1000 } });
  const target = await context.newPage();
  const errors = [];
  target.on("pageerror", error => errors.push(error.message));
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const origin = "http://127.0.0.1:8192";
  const definitions = await context.request.get(`${origin}/temp/node-definitions.json`).then(response => response.json());
  await context.route("**/extensions/ComfyUI-yton-nodes/**", async route => {
    const relative = new URL(route.request().url()).pathname.split("/extensions/ComfyUI-yton-nodes/")[1];
    await route.fulfill({ response: await context.request.get(`${origin}/web/${relative}`) });
  });
  await context.route("**/object_info**", async route => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), ...definitions } });
  });
  await context.route("**/settings**", async route => {
    if (route.request().method() === "POST") await route.fulfill({ json: {} });
    else await route.continue();
  });
  try {
    await target.goto("http://127.0.0.1:8188/", { waitUntil: "domcontentloaded" });
    await target.waitForFunction(() => window.LiteGraph?.registered_node_types?.YtonMiniMaxH3ReferenceToVideo);
    await target.getByRole("button", { name: "运行", exact: true }).first().waitFor();
    const result = await target.evaluate(async () => {
      const app = window.comfyAPI.app.app;
      app.graph.clear();
      const loader = LiteGraph.createNode("YtonEasyMediaLoader");
      const reference = LiteGraph.createNode("YtonMiniMaxH3ReferenceToVideo");
      loader.pos = [50, 40];
      reference.pos = [760, 40];
      app.graph.add(loader);
      app.graph.add(reference);
      for (const [index, name] of ["image", "video", "audio"].entries()) {
        loader.connect(index, reference, reference.inputs.findIndex(input => input.name === name));
      }
      reference.widgets.find(widget => widget.name === "prompt").value = "<Picture 1> <Video 1> <Audio 1>";
      reference.widgets.find(widget => widget.name === "length").value = 243;
      const saved = reference.serialize();
      reference.configure(saved);
      const before = (await app.graphToPrompt()).output[reference.id];
      const workflow = app.graph.serialize();
      app.graph.clear();
      app.graph.configure(workflow);
      const restored = app.graph.getNodeById(saved.id);
      const after = (await app.graphToPrompt()).output[restored.id];
      return {
        title: restored.title,
        inputs: restored.inputs.map(input => ({ name: input.name, type: input.type, shape: input.shape, link: input.link })),
        outputs: restored.outputs.map(output => output.type),
        before, after, loaderId: loader.id,
      };
    });
    assert(result.title === "MiniMax H3 参考生成视频", "Chinese node title must match");
    assert(result.outputs.join(",") === "CONDITIONING,LATENT", "Official outputs must be preserved");
    for (const [index, name] of ["image", "video", "audio"].entries()) {
      const input = result.inputs.find(input => input.name === name);
      assert(input.shape === 6 && input.link != null, `${name} must have a connected list socket`);
      assert(JSON.stringify(result.after.inputs[name]) === JSON.stringify([String(result.loaderId), index]), `${name} must reach the submitted prompt`);
    }
    assert(!result.inputs.filter(input => ["clip", "vae", "audio_vae"].includes(input.name)).some(input => input.shape === 6), "Scalar model sockets must retain their normal shape");
    assert(result.after.inputs.length === 243, "Length must reach the submitted prompt");
    assert(JSON.stringify(result.before) === JSON.stringify(result.after), "Save/reload must preserve all inputs and connections");
    assert(!errors.some(error => /yton|minimax_h3_reference/i.test(error)), `Node errors: ${errors.join("\n")}`);
    return result;
  } finally {
    await context.close();
  }
}
