async (page) => {
  const context = await page.context().browser().newContext({ viewport: { width: 1440, height: 1000 } });
  const target = await context.newPage();
  const errors = [];
  target.on("pageerror", error => {
    if (/yton|node_panel|ResizeObserver/i.test(error.stack || error.message)) errors.push(error.message);
  });
  // Serve the edited extension against the running ComfyUI without installing it.
  await context.route("**/extensions/ComfyUI-yton-nodes/**", async route => {
    const relative = new URL(route.request().url()).pathname.split("/extensions/ComfyUI-yton-nodes/")[1];
    const response = await context.request.get(`http://127.0.0.1:8192/${relative}`);
    await route.fulfill({ response });
  });
  // Renderer preferences stay within this isolated browser session.
  await context.route("**/settings**", async route => {
    if (route.request().method() === "POST") await route.fulfill({ json: {} });
    else await route.continue();
  });
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const checks = [];
  try {
    await target.goto("http://127.0.0.1:8188/", { waitUntil: "domcontentloaded" });
    await target.waitForFunction(() => window.LiteGraph?.registered_node_types?.YtonResolutionSelector);
    await target.getByRole("button", { name: "运行", exact: true }).first().waitFor();
    await target.evaluate(() => {
      const app = window.comfyAPI.app.app;
      app.graph.clear();
      const node = LiteGraph.createNode("YtonResolutionSelector");
      node.pos = [200, 100];
      app.graph.add(node);
      app.canvas.ds.offset = [0, 0];
      app.canvas.ds.scale = 1;
      window.ytonTestNode = node;
      app.canvas.setDirty(true, true);
    });
    const panel = target.locator(".yton-resolution-panel");
    await panel.waitFor({ state: "visible" });
    const fit = async () => {
      await target.waitForFunction(() => {
        const panel = document.querySelector(".yton-resolution-panel");
        if (!panel) return false;
        const shell = panel.parentElement;
        return panel.offsetWidth >= 300 && shell.scrollHeight <= shell.clientHeight + 1 && shell.scrollWidth <= shell.clientWidth + 1;
      });
      return panel.evaluate(el => ({ width: el.offsetWidth, height: el.offsetHeight }));
    };
    checks.push({ name: "new-node", ...await fit() });
    assert(await panel.locator(".yton-pill-btn").filter({ hasText: /^360p/ }).count() === 0, "H3 mode must omit 360p");
    const h3Preset = panel.locator(".yton-pill-btn").filter({ hasText: /^768p/ });
    assert(await h3Preset.innerText() === "768p\n(1.0)", "H3 mode must show the 768p multiplier as 1.0");
    await h3Preset.click();
    const h3Prompt = await target.evaluate(async () => (await window.comfyAPI.app.app.graphToPrompt()).output[window.ytonTestNode.id]);
    assert(h3Prompt.inputs.resolution === "768p", "The 768p selection must reach the generated prompt");
    await panel.getByRole("button", { name: "普通 / 图片", exact: true }).click();
    assert(await panel.locator(".yton-pill-btn").filter({ hasText: /^360p|^768p/ }).count() === 0, "Image mode must omit 360p and the H3-only 768p preset");
    const imagePrompt = await target.evaluate(async () => (await window.comfyAPI.app.app.graphToPrompt()).output[window.ytonTestNode.id]);
    assert(imagePrompt.inputs.resolution === "480p", "Switching from H3 768p must select the first valid image preset");
    await panel.getByRole("button", { name: "MiniMax H3", exact: true }).click();
    assert(await panel.locator(".yton-pill-btn").filter({ hasText: /^360p/ }).count() === 0, "H3 mode must omit 360p after switching modes");
    assert(await panel.locator(".yton-pill-btn").filter({ hasText: /^768p/ }).count() === 1, "H3 mode must include 768p after switching modes");
    await panel.getByRole("button", { name: "普通 / 图片", exact: true }).click();
    await panel.getByRole("button", { name: "6K", exact: true }).click();
    await panel.getByRole("button", { name: "画面比例 9:16", exact: true }).click();
    checks.push({ name: "normal-mode", ...await fit() });
    const saved = await target.evaluate(() => window.ytonTestNode.serialize());
    assert(JSON.stringify(saved.widgets_values) === JSON.stringify(["Normal (Standard Image/Video)", "9:16", "6K", 0, 0]), "UI must serialize only the five backend inputs");
    await target.evaluate(saved => {
      const node = window.ytonTestNode;
      node.widgets.find(w => w.name === "mode").value = "MiniMax H3 (Video)";
      node.widgets.find(w => w.name === "resolution").value = "1080p";
      node.widgets.find(w => w.name === "aspect_ratio").value = "16:9";
      node.configure(saved);
    }, saved);
    assert(await panel.getByRole("button", { name: "普通 / 图片", exact: true }).getAttribute("aria-pressed") === "true", "Restored mode must be selected");
    assert(await panel.getByRole("button", { name: "6K", exact: true }).getAttribute("aria-pressed") === "true", "Restored resolution must be selected");
    assert(await panel.getByRole("button", { name: "画面比例 9:16", exact: true }).getAttribute("aria-pressed") === "true", "Restored ratio must be selected");
    await panel.getByRole("button", { name: "MiniMax H3", exact: true }).click();
    assert(await panel.locator(".yton-pill-btn.active").innerText().then(text => text.startsWith("480p")), "Switching modes must select a valid preset in the new mode");
    await panel.locator(".yton-pill-btn").filter({ hasText: /^720p/ }).click();
    const prompt = await target.evaluate(async () => {
      const app = window.comfyAPI.app.app;
      const prompt = await app.graphToPrompt();
      return prompt.output[window.ytonTestNode.id];
    });
    assert(prompt.inputs.resolution === "720p" && prompt.inputs.aspect_ratio === "9:16", "Submitted prompt must match the visible choices");
    assert(!("resolution_ui" in prompt.inputs), "Custom UI must not be submitted as an input");
    await target.evaluate(() => {
      const widget = window.ytonTestNode.widgets.find(w => w.name === "resolution");
      widget.value = "540p";
      widget.callback(widget.value);
    });
    assert(await panel.locator(".yton-pill-btn.active").innerText().then(text => text.startsWith("540p")), "External widget changes must refresh the selection");
    for (const vue of [false, true]) {
      await target.evaluate(vue => window.comfyAPI.app.app.extensionManager.setting.set("Comfy.VueNodes.Enabled", vue), vue);
      for (const [width, height, scale] of [[1000, 800, 0.7], [1440, 1000, 1], [1920, 1080, 1.25]]) {
        await target.setViewportSize({ width, height });
        await target.evaluate(scale => {
          const app = window.comfyAPI.app.app;
          window.ytonTestNode.setSize([180, 180]);
          app.canvas.ds.scale = scale;
          app.canvas.setDirty(true, true);
        }, scale);
        checks.push({ name: vue ? "vue-node" : "canvas-node", viewport: [width, height], scale, ...await fit() });
        if (vue) {
          const bounds = await panel.evaluate(el => {
            const node = el.closest("[data-node-id]");
            const outer = node.getBoundingClientRect();
            const inner = el.getBoundingClientRect();
            return { bottom: inner.bottom <= outer.bottom + 1, right: inner.right <= outer.right + 1 };
          });
          assert(bounds.bottom && bounds.right, "Vue panel must stay inside its node");
        }
      }
    }
    await target.evaluate(() => {
      const app = window.comfyAPI.app.app;
      const media = LiteGraph.createNode("YtonEasyMediaLoader");
      media.pos = [620, 100];
      app.graph.add(media);
      app.canvas.ds.scale = 0.8;
      app.canvas.setDirty(true, true);
    });
    await target.waitForFunction(() => [...document.querySelectorAll(".yton-panel:not(.yton-resolution-panel)")].some(el => el.parentElement.clientHeight >= el.offsetHeight));
    const empty = target.locator(".yton-media-empty");
    assert(await empty.count() === 3, "New media loader must render all three empty categories");
    assert(errors.length === 0, `Extension errors: ${errors.join(", ")}`);
    return { passed: true, checks, promptInputs: prompt.inputs };
  } finally {
    await context.close();
  }
}
