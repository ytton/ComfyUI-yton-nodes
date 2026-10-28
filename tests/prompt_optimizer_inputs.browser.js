async (page) => {
  const context = await page.context().browser().newContext({ viewport: { width: 1440, height: 1000 } });
  const target = await context.newPage();
  try {
    await target.goto("http://127.0.0.1:8188/", { waitUntil: "domcontentloaded" });
    await target.waitForFunction(() => window.LiteGraph?.registered_node_types.YtonPromptOptimizer
      && window.LiteGraph.registered_node_types.YtonLlamaCppOptimizer && window.comfyAPI?.app?.app?.graph);
    await target.getByRole("button", { name: "运行", exact: true }).first().waitFor();
    const checks = await target.evaluate(async () => {
      const app = window.comfyAPI.app.app;
      const assert = (condition, message) => { if (!condition) throw new Error(message); };
      const checks = [];
      for (const type of ["YtonPromptOptimizer", "YtonLlamaCppOptimizer"]) {
        app.graph.clear();
        let node = LiteGraph.createNode(type);
        node.pos = [550, 80];
        app.graph.add(node);
        const editors = () => node.widgets.find(widget => widget.name === "prompt_optimizer_ui").element;
        const inputs = () => node.inputs.filter(input => ["prompt", "rules"].includes(input.name));
        const local = { prompt: "本地用户提示词", rules: "本地系统提示词" };
        for (const [name, value] of Object.entries(local)) node.widgets.find(widget => widget.name === name).value = value;
        node.onConfigure(node.serialize());
        assert(inputs().length === 2 && inputs().every(input => !input.widget), `${type}: text sockets must be independent of hidden widgets`);
        let submitted = (await app.graphToPrompt()).output[node.id].inputs;
        assert(submitted.prompt === local.prompt && submitted.rules === local.rules, `${type}: unconnected inputs must use local text`);
        const sourceIds = {};
        for (const name of ["prompt", "rules"]) {
          const source = LiteGraph.createNode("PrimitiveStringMultiline");
          source.pos = [60, name === "prompt" ? 80 : 360];
          app.graph.add(source);
          source.widgets.find(widget => widget.name === "value").value = `连线${name}测试`;
          sourceIds[name] = String(source.id);
          assert(source.connect(0, node, node.inputs.findIndex(input => input.name === name)), `${type}: ${name} must accept STRING`);
        }
        submitted = (await app.graphToPrompt()).output[node.id].inputs;
        for (const name of ["prompt", "rules"]) {
          assert(JSON.stringify(submitted[name]) === JSON.stringify([sourceIds[name], 0]), `${type}: ${name} must submit the upstream link`);
        }
        assert(editors().querySelector(".yton-ai-prompt").disabled && editors().querySelector(".yton-ai-rules").disabled,
          `${type}: connected editors must be disabled`);
        const id = node.id;
        const saved = JSON.parse(JSON.stringify(app.graph.serialize()));
        app.graph.clear();
        app.graph.configure(saved);
        node = app.graph.getNodeById(id);
        assert(inputs().length === 2 && inputs().every(input => !input.widget), `${type}: reopening must keep both sockets visible without duplicates`);
        submitted = (await app.graphToPrompt()).output[id].inputs;
        for (const name of ["prompt", "rules"]) {
          assert(JSON.stringify(submitted[name]) === JSON.stringify([sourceIds[name], 0]), `${type}: reopened ${name} link must survive`);
          node.disconnectInput(node.inputs.findIndex(input => input.name === name));
        }
        assert(!editors().querySelector(".yton-ai-prompt").disabled && !editors().querySelector(".yton-ai-rules").disabled,
          `${type}: disconnecting must enable the editors`);
        submitted = (await app.graphToPrompt()).output[id].inputs;
        assert(submitted.prompt === local.prompt && submitted.rules === local.rules, `${type}: disconnecting must restore local text`);
        checks.push({ type, visibleInputs: inputs().map(input => input.label), connected: true, reopened: true, disconnected: true });
      }
      app.canvas.ds.offset = [0, 0];
      app.canvas.ds.scale = 1;
      app.canvas.setDirty(true, true);
      return checks;
    });
    return { passed: true, checks };
  } finally {
    await context.close();
  }
}
