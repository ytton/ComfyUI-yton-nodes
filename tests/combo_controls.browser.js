// Use a separate browser context so the user's open workflows remain untouched.
export async function runComboControls(page, definitions, baseURL = "http://127.0.0.1:8188") {
  const context = await page.context().browser().newContext();
  const p = await context.newPage();
  const errors = [];
  p.on("pageerror", error => errors.push(error.message));
  await context.route(/\/(?:api\/)?object_info(?:\/[^?]+)?(?:\?.*)?$/, async route => {
    const response = await route.fetch();
    const json = await response.json();
    for (const definition of definitions) json[definition.name] = { ...definition, python_module: "custom_nodes.ComfyUI-yton-nodes" };
    await route.fulfill({ response, json });
  });
  await context.route("**/userdata/**", route => route.request().method() === "GET" ? route.continue() : route.fulfill({ json: {} }));
  await context.route(/\/(?:api\/)?settings(?:\/|$)/, route => route.request().method() === "POST" ? route.fulfill({ json: {} }) : route.continue());
  try {
    await p.goto(baseURL);
    await p.waitForFunction(() => window.LiteGraph?.registered_node_types.YtonComboClone && window.LiteGraph?.registered_node_types.YtonModeParameters, null, { timeout: 60000 });
    await p.waitForFunction(() => !!window.comfyAPI?.app?.app?.canvas?.canvas?.isConnected, null, { timeout: 60000 });
    const result = await p.evaluate(async () => {
      const assert = (condition, message) => { if (!condition) throw Error(message); };
      const app = window.comfyAPI.app.app;
      app.graph.clear();
      const add = type => { const node = LiteGraph.createNode(type); app.graph.add(node); return node; };
      let clone = add("YtonComboClone");
      const cloneId = clone.id;
      let sampler = add("KSampler");
      const samplerId = sampler.id;
      const samplerSlot = sampler.findInputSlot("sampler_name");
      sampler.widgets.find(w => w.name === "sampler_name").value = "heun";
      assert(clone.outputs[0].type === "COMBO", "clone exposes a COMBO socket");
      assert(clone.connect(0, sampler, samplerSlot), "clone connects directly to KSampler");
      let widget = clone.widgets.find(w => w.name === "value");
      assert(widget.options.values.includes("euler") && widget.options.values.includes("heun"), "reads real sampler options");
      assert(widget.value === "heun", "adopts target's selected value on first connection");
      widget.value = "euler";
      const another = add("KSampler");
      assert(clone.connect(0, another, another.findInputSlot("sampler_name")), "shares identical dropdown choices");
      assert(!clone.connect(0, another, another.findInputSlot("scheduler")), "rejects dropdowns with no common values");
      assert(!clone.connect(0, sampler, sampler.findInputSlot("steps")), "does not connect to numeric inputs");
      let api = (await app.graphToPrompt()).output;
      assert(api[cloneId].inputs.value === "euler", "exports selected value");
      assert(api[samplerId].inputs.sampler_name[0] === String(cloneId), "exports real combo link");
      const saved = app.graph.serialize();
      app.graph.configure(saved);
      app.extensions.find(extension => extension.name === "yton.ComboClone").afterConfigureGraph();
      app.extensions.find(extension => extension.name === "yton.ModeParameters").afterConfigureGraph();
      clone = app.graph.getNodeById(cloneId);
      sampler = app.graph.getNodeById(samplerId);
      widget = clone.widgets.find(w => w.name === "value");
      assert(widget.value === "euler" && widget.options.values.includes("heun"), "restores choice and live options after reload");
      clone.disconnectOutput(0);
      const loader = add("UNETLoader");
      assert(clone.connect(0, loader, loader.findInputSlot("unet_name")), "reconnects to model dropdown");
      assert(widget.options.values.length > 0 && widget.options.values.every(value => typeof value === "string"), "reads model filenames");
      const modelCount = widget.options.values.length;
      const modelChoice = widget.value;
      const map = add("YtonModeParameters");
      map.ytonModeParameters.configure({
        options: [{ id: "a", label: "euler" }, { id: "b", label: "heun" }],
        outputs: [{ id: "sampler", label: "采样器", type: "STRING" }, { id: "scheduler", label: "调度器", type: "STRING" }],
        values: { a: { sampler: "euler", scheduler: "normal" }, b: { sampler: "heun", scheduler: "karras" } },
      });
      assert(map.connect(0, sampler, sampler.findInputSlot("sampler_name")), "mode string connects to combo");
      assert(map.connect(2, sampler, sampler.findInputSlot("sampler_name")), "text parameter connects to combo");
      assert(map.connect(3, sampler, sampler.findInputSlot("scheduler")), "text parameter connects to scheduler");
      const text = add("StringContains");
      assert(map.connect(2, text, text.findInputSlot("string")), "same text parameter also connects to STRING");
      assert(!map.connect(2, sampler, sampler.findInputSlot("steps")), "text output retains numeric type boundaries");
      const mapId = map.id, textId = text.id;
      app.graph.configure(app.graph.serialize());
      app.extensions.find(extension => extension.name === "yton.ComboClone").afterConfigureGraph();
      app.extensions.find(extension => extension.name === "yton.ModeParameters").afterConfigureGraph();
      const restored = app.graph.getNodeById(mapId);
      const reordered = restored.ytonModeParameters.getConfig();
      reordered.outputs.reverse();
      restored.ytonModeParameters.configure(reordered);
      api = (await app.graphToPrompt()).output;
      assert(api[samplerId].inputs.sampler_name[1] === 3 && api[textId].inputs.string[1] === 3, "reordering preserves both combo and string wires");
      assert(api[samplerId].inputs.scheduler[1] === 2, "scheduler follows reordered field");
      const field = reordered.outputs.find(f => f.id === "sampler");
      field.type = "INT";
      for (const row of Object.values(reordered.values)) row.sampler = 1;
      restored.ytonModeParameters.configure(reordered);
      assert(app.graph.getNodeById(textId).inputs[text.findInputSlot("string")].link == null, "changing to INT disconnects text wire");
      const comboMap = add("YtonModeParameters");
      comboMap.ytonModeParameters.configure({
        options: [{ id: "a", label: "模式 A" }, { id: "b", label: "模式 B" }],
        outputs: [{ id: "sampler", label: "采样器选项", type: "COMBO" }],
        values: { a: { sampler: "" }, b: { sampler: "" } },
      });
      assert(comboMap.outputs[2].type === "COMBO", "mapping field exposes COMBO");
      assert(comboMap.connect(2, sampler, sampler.findInputSlot("sampler_name")), "mapping COMBO connects to sampler");
      assert(comboMap.ytonModeParameters.getConfig().values.a.sampler === "heun", "connection initializes valid choices for each mode");
      comboMap.ytonModeParameters.openSettings();
      const dialog = document.querySelector(".yton-mode-dialog");
      [...dialog.querySelectorAll("nav button")].find(button => button.textContent.includes("参数值")).click();
      let select = dialog.querySelector('select[aria-label="采样器选项"]');
      assert(select && !select.disabled && [...select.options].some(option => option.textContent === "euler"), "settings reads the connected dropdown's choices");
      select.value = [...select.options].find(option => option.textContent === "euler").value;
      select.dispatchEvent(new Event("change"));
      [...dialog.querySelectorAll(".yton-mode-value-options button")].find(button => button.textContent === "模式 B").click();
      select = dialog.querySelector('select[aria-label="采样器选项"]');
      assert(select.options[select.selectedIndex].textContent === "heun", "each mode has its own selected value");
      [...dialog.querySelectorAll("footer button")].find(button => button.textContent === "保存配置").click();
      const comboConfig = comboMap.ytonModeParameters.getConfig();
      assert(comboConfig.values.a.sampler === "euler" && comboConfig.values.b.sampler === "heun", "saves per-mode combo choices");
      const comboId = comboMap.id;
      app.graph.configure(app.graph.serialize());
      app.extensions.find(extension => extension.name === "yton.ComboClone").afterConfigureGraph();
      app.extensions.find(extension => extension.name === "yton.ModeParameters").afterConfigureGraph();
      assert(app.graph.getNodeById(comboId).ytonModeParameters.getConfig().values.a.sampler === "euler", "reload retains per-mode combo choices");
      return { modelCount, modelChoice, checks: "COMBO socket, target choices, initial selection, shared targets, incompatible inputs, prompt export, workflow reload, model dropdown, mode/text to COMBO and STRING, reorder, type change, mapping settings clone choices, per-mode dropdown selection" };
    });
    const relevant = errors.filter(error => /combo_clone|mode_parameters|ComboClone|ModeParameters/.test(error));
    if (relevant.length) throw Error(relevant.join("\n"));
    return { ...result, errors: relevant };
  } catch (error) {
    throw Error(error.message + "\nPage errors: " + errors.join("\n"));
  } finally {
    await context.close();
  }
}
