export async function checkPgsReferenceEditor(page) {
  const assert = (value, message) => { if (!value) throw Error(message); };
  const rich = page.locator(".pgs-rich-editor");
  const items = page.locator(".pgs-alias-menu .pgs-alias-item");
  const outputs = await page.evaluate(async () => {
    const { app, editor, collection } = window.pgsTest;
    const { output } = await app.graphToPrompt();
    return { types: collection.outputs.map(o => o.type), promptSource: output[editor.id].inputs.assets };
  });
  assert(outputs.types.join(",") === "H3_REFERENCE_ASSETS,H3_PGS_ASSETS", "generation and PGS have separate typed outputs");
  assert(outputs.promptSource[1] === 1, "the prompt editor uses the PGS schedule output");
  await rich.fill("@");
  await items.first().waitFor();
  assert(await items.count() === 4, "two images, video and audio appear in the @ menu");
  await items.filter({ hasText: "Picture_1" }).click();
  await rich.locator('.pgs-token[title="@Picture_1 → <Picture 1>"]').waitFor();
  const prompt = await page.evaluate(() => window.pgsTest.editor.widgets.find(w => w.name === "prompt").value);
  assert(prompt.includes("@Picture_1"), "choosing a reference updates the serialized prompt");
  await rich.locator(".pgs-token").hover();
  await page.locator("#pgs-popover img").waitFor();
  await page.waitForFunction(() => { const img = document.querySelector("#pgs-popover img"); return img?.complete && img.naturalWidth > 0; });
  await page.mouse.move(1700, 20);

  await page.evaluate(() => {
    const { app, collection } = window.pgsTest;
    const slot = collection.inputs.findIndex(i => i.name.startsWith("images.") && i.link == null);
    app.graph.getNodeById("518").connect(0, collection, slot);
  });
  await page.waitForFunction(() => window.pgsTest.editor.widgets.find(w => w.name === "pgs_scene_editor")
    .element.querySelector(".pgs-rich-editor").textContent.includes("@Picture_1"));
  await page.getByRole("button", { name: "🔄 刷新", exact: true }).click();
  await rich.fill("@");
  await items.first().waitFor();
  assert(await items.count() === 5, "adding a dynamic reference adds an @ option");
  await page.keyboard.press("Escape");

  await page.evaluate(() => {
    const { app, collection } = window.pgsTest;
    for (let i = collection.inputs.length - 1; i >= 0; i--) {
      if (collection.inputs[i].name.startsWith("images.") && collection.inputs[i].link != null) collection.disconnectInput(i);
    }
    const first = LiteGraph.createNode("MiniMaxH3RefPGSPictureAsset");
    const second = LiteGraph.createNode("MiniMaxH3RefPGSPictureAsset");
    app.graph.add(first); app.graph.add(second);
    first.widgets.find(w => w.name === "alias").value = "Hero";
    first.widgets.find(w => w.name === "label").value = "人物";
    second.widgets.find(w => w.name === "alias").value = "Scene";
    second.widgets.find(w => w.name === "label").value = "场景";
    app.graph.getNodeById("518").connect(0, first, first.findInputSlot("image"));
    app.graph.getNodeById("495").connect(0, second, second.findInputSlot("image"));
    first.connect(0, second, second.findInputSlot("previous"));
    second.connect(0, collection, collection.findInputSlot("pgs_images"));
    window.pgsTest.marker = first;
  });
  await page.getByRole("button", { name: "🔄 刷新", exact: true }).click();
  await rich.fill("@");
  await items.first().waitFor();
  assert(await items.count() === 4, "native PGS markers replace direct image options without duplicates");
  await items.filter({ hasText: "Hero" }).click();
  await rich.locator('.pgs-token[title="@Hero → <Picture 1>"]').waitFor();
  const wiring = await page.evaluate(async () => {
    const { app, collection, marker } = window.pgsTest;
    const { output } = await app.graphToPrompt();
    marker.widgets.find(w => w.name === "alias").value = "Person";
    return { collection: output[collection.id].inputs, markers: Object.values(output).filter(n => n.class_type === "MiniMaxH3RefPGSPictureAsset").length };
  });
  assert(wiring.collection.pgs_images && wiring.markers === 2, "the marker chain enters the actual execution graph");
  await page.waitForFunction(() => !document.querySelector('.pgs-rich-editor .pgs-token[title^="@Hero"]'));
  await rich.fill("@"); await items.first().waitFor();
  await items.filter({ hasText: "Person" }).click();
  const saved = await page.evaluate(() => window.pgsTest.app.graph.serialize());
  await page.evaluate(async workflow => {
    const app = window.pgsTest.app;
    await app.loadGraphData(workflow);
    window.pgsTest = { app, editor: app.graph.getNodeById("524"), collection: app.graph.getNodeById("639") };
  }, saved);
  await rich.locator('.pgs-token[title="@Person → <Picture 1>"]').waitFor();
  await rich.fill("@"); await items.first().waitFor();
  assert(await items.count() === 4, "@ references remain available after serialization and reload");
  await page.keyboard.press("Escape");
  return { menu: true, insert: true, preview: true, dynamic: true, pgsMarkers: true, rename: true, reload: true };
}
