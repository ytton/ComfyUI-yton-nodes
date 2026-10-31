export async function checkH3Studio(page, definition, imageBase64) {
  const context = await page.context().browser().newContext({ viewport: { width: 1800, height: 1300 } });
  const p = await context.newPage();
  const errors = [];
  p.on("pageerror", error => { if (/h3_reference_studio|media_loader_panel|node_panel/i.test(error.stack || "")) errors.push(error.message); });
  await context.route(/\/(?:api\/)?object_info(?:\/[^?]+)?(?:\?.*)?$/, async route => {
    const response = await route.fetch();
    const data = await response.json(); data[definition.name] = definition;
    await route.fulfill({ response, json: data });
  });
  await context.route("**/userdata/**", route => route.request().method() === "GET" ? route.continue() : route.fulfill({ json: {} }));
  await context.route(/\/(?:api\/)?settings(?:\/|$)/, route => route.request().method() === "POST" ? route.fulfill({ json: {} }) : route.continue());
  await context.route(/\/(?:api\/)?prompt$/, route => route.request().method() === "POST" ? route.abort() : route.continue());
  const imageBuffer = Buffer.from(imageBase64, "base64");
  let uploads = 0;
  await context.route("**/upload/image", route => route.fulfill({ json: { name: `studio-${++uploads}.png`, subfolder: "yton-media", type: "input" } }));
  await context.route("**/view?**", route => route.fulfill({ contentType: "image/png", body: imageBuffer }));
  const assert = (value, message) => { if (!value) throw Error(message); };
  try {
    await p.goto("http://127.0.0.1:8188/");
    await p.getByTestId("workflows-tab-button").waitFor({ timeout: 60000 });
    await p.waitForFunction(() => window.LiteGraph?.registered_node_types.YtonH3ReferenceStudio);
    await p.evaluate(() => {
      const app = window.comfyAPI.app.app;
      app.graph.clear();
      const node = LiteGraph.createNode("YtonH3ReferenceStudio");
      app.graph.add(node); node.pos = [110, 160];
      const model = LiteGraph.createNode("CheckpointLoaderSimple");
      app.graph.add(model); model.pos = [1500, 700];
      model.connect(1, node, node.findInputSlot("clip"));
      model.connect(2, node, node.findInputSlot("vae"));
      model.connect(2, node, node.findInputSlot("audio_vae"));
      app.canvas.ds.scale = 0.9; app.canvas.ds.offset = [0, 0];
      window.studioTestNode = node;
      app.canvas.draw(true, true);
    });
    const panel = p.locator(".yton-h3-studio");
    await panel.waitFor({ state: "visible" });
    await panel.locator(".yton-h3-size-info").first().getByText("1344 × 768", { exact: false }).waitFor();
    await panel.getByRole("textbox", { name: "提示词", exact: true }).fill("用 <Picture 1> 生成视频");
    await panel.locator('[data-value="1080p"]').click();
    await panel.locator('[data-value="9:16"]').click();
    assert((await panel.locator(".yton-h3-size-info").first().textContent()).includes("1088 × 1920"), "resolution and ratio combine");
    assert((await panel.locator('[data-value="1080p"]').textContent()).includes("MP"), "resolution displays megapixels");
    const ref = panel.locator(".yton-h3-section").filter({ has: p.getByText("参考图尺寸", { exact: true }) });
    await ref.getByRole("button", { name: "自定义", exact: true }).click();
    await ref.getByRole("spinbutton").fill("0.75");
    await ref.getByRole("spinbutton").press("Tab");
    await ref.locator('[data-value="max"]').click();
    assert(!await ref.locator(".yton-h3-custom-choice").evaluate(tile => tile.classList.contains("active")), "max deselects the custom scale tile");
    assert(await ref.getByRole("spinbutton").isVisible(), "custom scale stays directly editable");
    await ref.locator('[data-value="match"]').click();
    await ref.getByRole("spinbutton").focus();
    assert(await ref.locator(".yton-h3-custom-choice").evaluate(tile => tile.classList.contains("active")), "editing custom scale selects its mode");
    const duration = panel.locator(".yton-h3-section").filter({ has: p.getByText("视频时长", { exact: true }) });
    await duration.getByRole("button", { name: "7.5 秒", exact: true }).click();
    assert((await duration.locator(".yton-h3-size-info").textContent()).includes("192 帧"), "fractional seconds show aligned frames");
    await duration.getByRole("spinbutton").focus();
    assert(await duration.locator(".yton-h3-custom-choice").evaluate(tile => tile.classList.contains("active")), "editing custom duration selects its mode");
    await duration.getByRole("spinbutton").fill("6.2");
    await duration.getByRole("spinbutton").press("Tab");
    const chooserEvent = p.waitForEvent("filechooser");
    await panel.locator('[data-slot="image_1"]').click();
    await (await chooserEvent).setFiles([{ name: "portrait.png", mimeType: "image/png", buffer: imageBuffer }, { name: "second.png", mimeType: "image/png", buffer: imageBuffer }]);
    await p.waitForFunction(() => window.studioTestNode.widgets.find(w => w.name === "image_2").value !== "");
    const image = panel.locator('[data-slot="image_1"] img.yton-media-thumb');
    await image.evaluate(img => img.decode());
    assert(await image.evaluate(img => getComputedStyle(img).objectFit === "contain"), "studio portrait preview uses contain");
    await panel.locator('[data-slot="image_1"]').dragTo(panel.locator('[data-slot="image_3"]'));
    await p.waitForFunction(() => window.studioTestNode.widgets.find(w => w.name === "image_3").value.includes("studio-1"));
    await panel.locator('[data-slot="image_3"]').hover();
    await panel.getByRole("button", { name: "禁用图片 3 输出", exact: true }).click();
    await panel.getByRole("button", { name: "参考视频 · 3", exact: true }).click();
    await panel.getByRole("button", { name: "参考音频 · 3", exact: true }).click();
    const before = await p.evaluate(async () => {
      const app = window.comfyAPI.app.app, node = window.studioTestNode;
      const prompt = (await app.graphToPrompt()).output[node.id].inputs;
      return { inputs: prompt, saved: app.graph.serialize(), id: node.id, size: [...node.size] };
    });
    assert(before.inputs.ref_scale === 0.75 && before.inputs.duration === 6.2, "UI writes actual node inputs");
    assert(before.inputs.disable_image_3 === true, "disabled media is serialized");
    assert(Array.isArray(before.inputs.clip) && Array.isArray(before.inputs.vae) && Array.isArray(before.inputs.audio_vae), "media editing preserves models");
    await p.evaluate(async ({ saved, id }) => {
      const app = window.comfyAPI.app.app;
      await app.loadGraphData(saved);
      window.studioTestNode = app.graph.getNodeById(id);
      app.canvas.ds.scale = 0.9; app.canvas.ds.offset = [0, 0];
      app.canvas.draw(true, true);
    }, before);
    await panel.getByRole("spinbutton", { name: "自定义秒数", exact: true }).waitFor();
    assert(await panel.getByRole("spinbutton", { name: "自定义秒数", exact: true }).inputValue() === "6.2", "duration survives reload");
    assert(await ref.getByRole("spinbutton").inputValue() === "0.75", "reference scale survives reload");
    const layout = await panel.evaluate(panel => {
      const controls = panel.querySelector(".yton-h3-controls").getBoundingClientRect();
      const media = panel.querySelector(".yton-h3-media").getBoundingClientRect();
      const output = panel.querySelector(".yton-h3-outputs").getBoundingClientRect();
      return { columns: controls.right < media.left && media.right < output.left, overflow: panel.scrollWidth > panel.clientWidth + 2 };
    });
    assert(layout.columns && !layout.overflow, "three columns follow the sketch without overflow");
    assert(await panel.locator(".yton-h3-ratios").evaluate(group => getComputedStyle(group).gridTemplateColumns.split(" ").length === 3), "nine aspect choices form a 3 by 3 grid");
    await p.evaluate(() => window.studioTestNode.setSize([860, window.studioTestNode.size[1]]));
    await p.waitForFunction(() => document.querySelector(".yton-h3-studio").clientWidth < 880);
    const grids = await panel.evaluate(panel => [
      [".yton-h3-tiers", 4, 3], [".yton-h3-ratios", 3, 3],
      [".yton-h3-durations", 3, 2], [".yton-h3-ref-size", 3, 1],
    ].map(([selector, columns, rows]) => {
      const group = panel.querySelector(selector), style = getComputedStyle(group);
      return style.gridTemplateColumns.split(" ").length === columns &&
        style.gridTemplateRows.split(" ").length === rows && group.scrollWidth <= group.clientWidth + 2;
    }));
    assert(grids.every(Boolean), "all choice grids stay aligned at minimum node width");
    await p.evaluate(() => window.studioTestNode.setSize([1080, window.studioTestNode.size[1]]));
    const wire = await p.evaluate(async () => {
      const app = window.comfyAPI.app.app, node = window.studioTestNode;
      const sink = LiteGraph.createNode("PrimitiveInt");
      app.graph.add(sink); sink.pos = [node.pos[0] + node.size[0] + 90, node.pos[1] + 300]; sink.convertWidgetToInput(sink.widgets[0]);
      window.studioIntSink = sink;
      app.canvas.ds.scale = 0.7; app.canvas.ds.offset = [20, 160];
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      app.canvas.draw(true, true);
      const rect = app.canvas.canvas.getBoundingClientRect();
      const point = p => ({ x: rect.x + (p[0] + app.canvas.ds.offset[0]) * app.canvas.ds.scale,
        y: rect.y + (p[1] + app.canvas.ds.offset[1]) * app.canvas.ds.scale });
      const output = node.getOutputPos(2);
      return { from: point(output), to: point(sink.getInputPos(0)),
        hit: node.getSlotInPosition(output[0], output[1])?.output?.type };
    });
    assert(wire.hit === "INT", "output hit target matches its visual row");
    await p.mouse.move(wire.from.x, wire.from.y); await p.mouse.down();
    await p.mouse.move(wire.to.x, wire.to.y, { steps: 12 }); await p.mouse.up();
    assert(await p.evaluate(() => window.studioIntSink.inputs[0].link != null), "actual width wire can be dragged from output rail");
    await p.evaluate(() => {
      const app = window.comfyAPI.app.app;
      const old = LiteGraph.createNode("YtonEasyMediaLoader");
      app.graph.add(old); old.pos = [100, 1100];
      const w = old.widgets.find(w => w.name === "image_1"); w.value = "yton-media/portrait.png"; w.callback?.(w.value);
      window.oldMediaTestNode = old;
      app.canvas.draw(true, true);
    });
    const fitModes = await p.locator("img.yton-media-thumb").evaluateAll(images => images.map(image => getComputedStyle(image).objectFit));
    assert(fitModes.length >= 2 && fitModes.every(mode => mode === "contain"), "both loaders contain their image previews");
    if (errors.length) throw Error(errors.join("\n"));
    return { title: "H3 参考视频工作台", checks: "layout, resolution/MP, reference modes, fractional/custom duration, uploads, drag/drop, disable, model links, save/reload, output wire, shared contain", size: before.size };
  } finally { await context.close(); }
}
