export async function runLocalOptimizer(page, fixtures) {
  const context = await page.context().browser().newContext({ viewport: { width: 1440, height: 1000 } });
  const p = await context.newPage();
  const errors = [];
  p.on("pageerror", error => errors.push(error.message));
  await context.route(/\/(?:api\/)?object_info(?:\/[^?]+)?(?:\?.*)?$/, async route => {
    const response = await route.fetch();
    const json = await response.json();
    Object.assign(json, fixtures.definitions);
    await route.fulfill({ response, json });
  });
  await context.route("**/userdata/**", route => route.request().method() === "GET" ? route.continue() : route.fulfill({ json: {} }));
  await context.route(/\/(?:api\/)?settings(?:\/|$)/, route => route.request().method() === "POST" ? route.fulfill({ json: {} }) : route.continue());
  for (const name of ["native", "llama"]) await context.route(`**/yton/prompt-optimizer/${name}`, route => route.fulfill({ json: fixtures[name] }));
  try {
    await p.goto("http://127.0.0.1:8188");
    await p.getByTestId("workflows-tab-button").waitFor({ timeout: 60000 });
    await p.evaluate(() => {
      const app = window.comfyAPI.app.app;
      app.graph.clear();
      const node = LiteGraph.createNode("YtonLocalPromptOptimizer");
      app.graph.add(node);
      node.pos = [550, 80];
      app.canvas.ds.offset = [0, 0];
      app.canvas.ds.scale = 1;
      window.localOptimizerId = node.id;
    });
    const backend = p.locator('summary[aria-label="本地推理方式"]');
    await backend.waitFor();
    if (!(await backend.textContent()).includes("ComfyUI 原生")) throw Error("native must be the initial backend");
    if (await p.getByText("请选择本地 GGUF 模型", { exact: true }).isVisible()) throw Error("GGUF choice should be hidden in native mode");
    const gear = p.getByRole("button", { name: "本地推理设置（当前节点）", exact: true });
    await gear.click();
    const dialog = p.getByRole("dialog", { name: "ComfyUI 原生推理设置", exact: true });
    await dialog.waitFor();
    await dialog.getByRole("spinbutton", { name: "最大输出 Token", exact: true }).fill("1024");
    await dialog.getByRole("checkbox", { name: "启用思考", exact: true }).check();
    if (await dialog.getByText("模型加载与显存", { exact: true }).count()) throw Error("native dialog must not expose llama load options");
    await p.screenshot({ path: "F:/ComfyUI/ComfyUI/custom_nodes/ComfyUI-yton-nodes/temp/local-optimizer-native-settings.png" });
    await dialog.getByRole("button", { name: "保存", exact: true }).click();
    await backend.click();
    await p.getByRole("button", { name: "llama.cpp · GGUF", exact: true }).click();
    await p.getByText("请选择本地 GGUF 模型", { exact: true }).click();
    await p.getByRole("button", { name: "test-model.gguf", exact: true }).click();
    await gear.click();
    const llama = p.getByRole("dialog", { name: "llama.cpp 推理设置", exact: true });
    await llama.getByRole("spinbutton", { name: "模型上下文", exact: true }).fill("8192");
    await llama.getByRole("button", { name: "保存", exact: true }).click();
    await backend.click();
    await p.getByRole("button", { name: "ComfyUI 原生 · CLIP", exact: true }).click();
    const result = await p.evaluate(async () => {
      const app = window.comfyAPI.app.app;
      let node = app.graph.getNodeById(window.localOptimizerId);
      const assert = (value, message) => { if (!value) throw Error(message); };
      const widget = name => node.widgets.find(widget => widget.name === name);
      assert(JSON.parse(widget("native_options_json").value).max_tokens === 1024, "native settings saved");
      assert(JSON.parse(widget("native_options_json").value).thinking === true, "native thinking saved");
      assert(JSON.parse(widget("options_json").value).n_ctx === 8192, "llama settings saved separately");
      const loader = LiteGraph.createNode("CLIPLoader");
      app.graph.add(loader);
      assert(loader.connect(0, node, node.findInputSlot("clip")), "CLIP must connect");
      widget("prompt").value = "本地用户提示词";
      node.onConfigure(node.serialize());
      const id = node.id;
      const serialized = app.graph.serialize();
      await app.loadGraphData(serialized);
      node = app.graph.getNodeById(id);
      const api = (await app.graphToPrompt()).output[id];
      assert(api.inputs.backend === "comfyui", "backend selection persisted");
      assert(api.inputs.clip?.[0] === String(loader.id), "CLIP connection persisted");
      assert(api.inputs.prompt === "本地用户提示词", "prompt preserved");
      assert(JSON.parse(api.inputs.native_options_json).max_tokens === 1024, "native settings persisted");
      assert(api.inputs.model_name === "test-model.gguf", "GGUF choice preserved independently");
      return { node: node.title, backend: api.inputs.backend, inputs: node.inputs.map(input => input.name) };
    });
    await p.screenshot({ path: "F:/ComfyUI/ComfyUI/custom_nodes/ComfyUI-yton-nodes/temp/local-optimizer-node.png" });
    const relevantErrors = errors.filter(message => /optimizer|structuredClone/.test(message));
    if (relevantErrors.length) throw Error(relevantErrors.join("\n"));
    return { ...result, checks: "rename, backend switching, native sampling/thinking, separate GGUF settings, native CLIP connection, workflow persistence", errors: relevantErrors };
  } catch (error) {
    const state = await p.locator('.yton-optimizer-panel,.yton-ai-dialog').evaluateAll(elements => elements.map(element => ({ text: element.innerText, html: element.outerHTML.slice(0, 1400) })));
    await p.screenshot({ path: "F:/ComfyUI/ComfyUI/custom_nodes/ComfyUI-yton-nodes/temp/local-optimizer-error.png" });
    throw Error(error.message + "\nUI: " + JSON.stringify(state) + "\nPage errors: " + errors.join("\n"));
  } finally {
    await context.close();
  }
}
