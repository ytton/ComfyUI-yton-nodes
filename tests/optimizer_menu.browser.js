export async function runOptimizerMenuOverflow(page) {
  const context = await page.context().browser().newContext({ viewport: { width: 1440, height: 1000 } });
  const p = await context.newPage();
  const model = "regression/Qwen-long-model-name-Q4_K_M.gguf";
  await context.route("**/userdata/**", route => route.request().method() === "GET" ? route.continue() : route.fulfill({ json: {} }));
  await context.route(/\/(?:api\/)?settings(?:\/|$)/, route => route.request().method() === "POST" ? route.fulfill({ json: {} }) : route.continue());
  await context.route("**/yton/prompt-optimizer/llama", route => route.fulfill({ json: {
    models: [model, ...Array.from({ length: 18 }, (_, i) => `regression/model-${i}.gguf`)],
  } }));
  try {
    await p.goto("http://127.0.0.1:8188");
    await p.getByTestId("workflows-tab-button").waitFor({ timeout: 60000 });
    await p.evaluate(() => {
      const app = window.comfyAPI.app.app;
      app.graph.clear();
      const node = LiteGraph.createNode("YtonLocalPromptOptimizer");
      app.graph.add(node);
      node.pos = [450, 60];
      app.canvas.ds.offset = [0, 0];
      app.canvas.ds.scale = 1;
      window.optimizerMenuTestId = node.id;
    });
    await p.locator('summary[aria-label="本地推理方式"]').click();
    await p.getByRole("button", { name: "llama.cpp · GGUF", exact: true }).click();
    const trigger = p.locator(".yton-ai-model-row summary");
    const popup = p.locator(".yton-ai-model-options:popover-open");
    await trigger.click();
    await p.getByRole("button", { name: model, exact: true }).waitFor();
    const overflow = await p.evaluate(() => {
      const popup = document.querySelector(".yton-ai-model-options:popover-open");
      const bounds = popup.getBoundingClientRect();
      const shell = popup.closest(".yton-widget-shell").getBoundingClientRect();
      const y = Math.max(shell.bottom + 10, bounds.top + 10);
      if (bounds.bottom <= shell.bottom || y >= bounds.bottom) throw Error("menu must extend below the clipped node");
      if (!popup.contains(document.elementFromPoint(bounds.left + 20, y))) throw Error("menu below node is clipped or cannot receive clicks");
      return { popup: bounds.toJSON(), shell: shell.toJSON() };
    });
    await p.screenshot({ path: "F:/ComfyUI/ComfyUI/custom_nodes/ComfyUI-yton-nodes/temp/optimizer-menu-overflow.png" });
    await p.evaluate(() => {
      const app = window.comfyAPI.app.app;
      app.canvas.ds.scale = .75;
      app.canvas.ds.offset = [120, 40];
      app.graph.setDirtyCanvas(true, true);
    });
    await p.waitForFunction(() => {
      const popup = document.querySelector(".yton-ai-model-options:popover-open");
      const anchor = popup.previousElementSibling.getBoundingClientRect();
      const bounds = popup.getBoundingClientRect();
      return Math.abs(bounds.left - anchor.left) < 1 && Math.abs(bounds.width - anchor.width) < 1 && Math.abs(bounds.top - anchor.bottom - 4) < 1;
    });
    await popup.hover();
    await p.mouse.wheel(0, 160);
    await p.waitForFunction(() => document.querySelector(".yton-ai-model-options:popover-open").scrollTop > 0);
    if (await p.evaluate(() => window.comfyAPI.app.app.canvas.ds.scale) !== .75) throw Error("scrolling menu changed canvas zoom");
    await p.getByRole("button", { name: model, exact: true }).click();
    await popup.waitFor({ state: "hidden" });
    const selected = await p.evaluate(() => window.comfyAPI.app.app.graph.getNodeById(window.optimizerMenuTestId).widgets.find(w => w.name === "model_name").value);
    if (selected !== model) throw Error("model selection was not saved");
    await trigger.click();
    await p.keyboard.press("Escape");
    await popup.waitFor({ state: "hidden" });
    await trigger.click();
    await p.mouse.click(100, 800);
    await popup.waitFor({ state: "hidden" });
    await p.evaluate(() => {
      const app = window.comfyAPI.app.app;
      app.canvas.ds.scale = 1;
      app.canvas.ds.offset = [0, 320];
      app.graph.setDirtyCanvas(true, true);
    });
    await trigger.click();
    await p.waitForFunction(() => {
      const popup = document.querySelector(".yton-ai-model-options:popover-open");
      return popup && popup.getBoundingClientRect().bottom <= popup.previousElementSibling.getBoundingClientRect().top;
    });
    await p.evaluate(() => {
      const app = window.comfyAPI.app.app;
      app.graph.remove(app.graph.getNodeById(window.optimizerMenuTestId));
    });
    await popup.waitFor({ state: "hidden" });
    return { selected, overflow, checks: "outside-node hit testing, zoom/pan anchoring, menu scroll, selection, Escape, outside click, viewport flip, node removal" };
  } finally {
    await context.close();
  }
}
