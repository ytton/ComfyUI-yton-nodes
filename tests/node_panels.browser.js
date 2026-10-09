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
    const checkWidth = async (selected) => {
      await target.evaluate(selected => {
        const app = window.comfyAPI.app.app;
        if (selected) app.canvas.selectNode(window.ytonTestNode);
        else app.canvas.deselectAllNodes();
        app.canvas.setDirty(true, true);
      }, selected);
      // The selected-node inspector mounts asynchronously and writes widget.width.
      await target.waitForTimeout(400);
      const dimensions = await panel.evaluate(el => {
        const node = window.ytonTestNode;
        const shell = el.parentElement;
        const widget = node.widgets.find(w => w.name === "resolution_ui");
        const vueNode = el.closest("[data-node-id]");
        const expectedWidth = node.size[0] - (vueNode ? 24 : 28);
        return {
          nodeWidth: node.size[0],
          widgetWidth: widget.width,
          panelWidth: el.offsetWidth,
          expectedWidth,
          shellOverflow: shell.scrollWidth > shell.clientWidth + 1,
        };
      });
      assert(Math.abs(dimensions.panelWidth - dimensions.expectedWidth) <= 1,
        `Panel must fill the node when selected=${selected}: ${JSON.stringify(dimensions)}`);
      assert(!dimensions.shellOverflow, "Panel must not overflow horizontally");
      return dimensions;
    };
    checks.push({ name: "new-node", ...await fit() });
    assert(await panel.locator(".yton-pill-btn").count() === 9, "H3 mode must show nine resolution presets");
    const h3GridHeight = await panel.locator(".yton-grid-pills").evaluate(el => el.offsetHeight);
    for (const [resolution, multiplier] of [["848p", "1.2"], ["944p", "1.5"], ["1024p", "1.8"]]) {
      const preset = panel.locator(".yton-pill-btn").filter({ hasText: new RegExp(`^${resolution}`) });
      assert(await preset.innerText() === `${resolution}\n(${multiplier})`, "H3 presets must display their multiplier");
      await preset.click();
      const submitted = await target.evaluate(async () => (await window.comfyAPI.app.app.graphToPrompt()).output[window.ytonTestNode.id]);
      assert(submitted.inputs.resolution === resolution, "The added H3 selection must reach the submitted prompt");
    }
    assert(await panel.locator(".yton-pill-btn").filter({ hasText: /^360p/ }).count() === 0, "H3 mode must omit 360p");
    const h3Preset = panel.locator(".yton-pill-btn").filter({ hasText: /^768p/ });
    assert(await h3Preset.innerText() === "768p\n(1.0)", "H3 mode must show the 768p multiplier as 1.0");
    await h3Preset.click();
    const h3Prompt = await target.evaluate(async () => (await window.comfyAPI.app.app.graphToPrompt()).output[window.ytonTestNode.id]);
    assert(h3Prompt.inputs.resolution === "768p", "The 768p selection must reach the generated prompt");
    await panel.getByRole("button", { name: "普通 / 图片", exact: true }).click();
    assert(await panel.locator(".yton-pill-btn").count() === 9, "Image mode must show nine resolution presets");
    const imageGridHeight = await panel.locator(".yton-grid-pills").evaluate(el => el.offsetHeight);
    assert(h3GridHeight === imageGridHeight, "Both resolution grids must have equal height");
    assert(await panel.locator(".yton-pill-btn").filter({ hasText: /^360p|^768p/ }).count() === 0, "Image mode must omit 360p and the H3-only 768p preset");
    const imagePrompt = await target.evaluate(async () => (await window.comfyAPI.app.app.graphToPrompt()).output[window.ytonTestNode.id]);
    assert(imagePrompt.inputs.resolution === "480p", "Switching from H3 768p must select the first valid image preset");
    assert(await panel.getByRole("button", { name: "1K", exact: true }).count() === 0, "Image mode must omit 1K");
    await panel.getByRole("button", { name: "2.5K", exact: true }).click();
    const image25kPrompt = await target.evaluate(async () => (await window.comfyAPI.app.app.graphToPrompt()).output[window.ytonTestNode.id]);
    assert(image25kPrompt.inputs.resolution === "2.5K", "The 2.5K selection must reach the submitted prompt");
    await panel.getByRole("button", { name: "MiniMax H3", exact: true }).click();
    assert(await panel.locator(".yton-pill-btn").filter({ hasText: /^360p/ }).count() === 0, "H3 mode must omit 360p after switching modes");
    assert(await panel.locator(".yton-pill-btn").filter({ hasText: /^768p/ }).count() === 1, "H3 mode must include 768p after switching modes");
    await panel.getByRole("button", { name: "普通 / 图片", exact: true }).click();
    assert(await panel.getByRole("button", { name: "2.5K", exact: true }).count() === 1, "Image mode must show 2.5K after switching modes");
    await panel.getByRole("button", { name: "2.5K", exact: true }).click();
    await panel.getByRole("button", { name: "画面比例 9:16", exact: true }).click();
    checks.push({ name: "normal-mode", ...await fit() });
    const saved = await target.evaluate(() => window.ytonTestNode.serialize());
    assert(JSON.stringify(saved.widgets_values) === JSON.stringify(["Normal (Standard Image/Video)", "9:16", "2.5K", 0, 0]), "UI must serialize only the five backend inputs");
    await target.evaluate(saved => {
      const node = window.ytonTestNode;
      node.widgets.find(w => w.name === "mode").value = "MiniMax H3 (Video)";
      node.widgets.find(w => w.name === "resolution").value = "1080p";
      node.widgets.find(w => w.name === "aspect_ratio").value = "16:9";
      node.configure(saved);
    }, saved);
    assert(await panel.getByRole("button", { name: "普通 / 图片", exact: true }).getAttribute("aria-pressed") === "true", "Restored mode must be selected");
    assert(await panel.getByRole("button", { name: "2.5K", exact: true }).getAttribute("aria-pressed") === "true", "Restored resolution must be selected");
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
        for (const selected of [true, false, true]) {
          checks.push({ name: vue ? "vue-selection" : "canvas-selection", scale, selected, ...await checkWidth(selected) });
        }
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
      for (const nodeWidth of [540, 420, 360]) {
        await target.evaluate(width => window.ytonTestNode.setSize([width, 600]), nodeWidth);
        checks.push({ name: vue ? "vue-resize-selected" : "canvas-resize-selected", ...await checkWidth(true) });
        checks.push({ name: vue ? "vue-resize-deselected" : "canvas-resize-deselected", ...await checkWidth(false) });
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
