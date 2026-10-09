async (page) => {
  const context = await page.context().browser().newContext({ viewport: { width: 1440, height: 1000 } });
  const target = await context.newPage();
  const errors = [];
  target.on("pageerror", error => errors.push(error.message));
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const imageBuffer = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAIAAAABgCAIAAABaGO0eAAAA7ElEQVR4nO3RMQ0AIADAMMAZ1pCIImT0YFWwZPOePeIsHfC7BmANwBqANQBrANYArAFYA7AGYA3AGoA1AGsA1gCsAVgDsAZgDcAagDUAawDWAKwBWAOwBmANwBqANQBrANYArAFYA7AGYA3AGoA1AGsA1gCsAVgDsAZgDcAagDUAawDWAKwBWAOwBmANwBqANQBrANYArAFYA7AGYA3AGoA1AGsA1gCsAVgDsAZgDcAagDUAawDWAKwBWAOwBmANwBqANQBrANYArAFYA7AGYA3AGoA1AGsA1gCsAVgDsAZgDcAagDUAawDWAOwBKjwCVRon3BkAAAAASUVORK5CYII=", "base64");
  const files = [];
  await context.route("**/yuan-director/bridge/state", route => route.fulfill({ json: { version: 1, task: null } }));
  await context.routeWebSocket(/\/ws(?:\?|$)/, () => {});
  await context.route("**/settings**", route => route.request().method() === "POST"
    ? route.fulfill({ json: {} }) : route.continue());
  let fileChoosers = 0;
  target.on("filechooser", () => fileChoosers++);
  const open = async index => {
    await target.locator(`[data-slot="image_${index}"]`).hover();
    await target.getByRole("button", { name: `编辑图片 ${index} 遮罩`, exact: true }).click();
    await target.locator(".mask-editor-dialog").waitFor();
    await target.locator('[data-testid="loading-overlay"]').waitFor({ state: "hidden" });
    await target.waitForFunction(() => document.querySelector(".mask-editor-dialog canvas")?.width === 128);
  };
  const cancel = async () => {
    await target.locator(".mask-editor-dialog button").filter({ hasText: /^\s*取消\s*$/ }).click();
    await target.locator(".mask-editor-dialog").waitFor({ state: "hidden" });
  };
  const values = () => target.evaluate(() => window.ytonMaskTestNode.widgets.filter(w => /^image_\d+$/.test(w.name)).map(w => w.value));
  try {
    const uploaded = await context.request.post("http://127.0.0.1:8188/upload/image", {
      multipart: { image: { name: `yton-mask-test-${Date.now()}.png`, mimeType: "image/png", buffer: imageBuffer }, type: "input", subfolder: "yton-mask-tests" },
    }).then(response => response.json());
    const filename = [uploaded.subfolder, uploaded.name].filter(Boolean).join("/");
    files.push(filename);
    await target.goto("http://127.0.0.1:8188");
    await target.getByRole("button", { name: "Yuan-Director 插件信息", exact: true }).waitFor();
    await target.evaluate(async filename => {
      const { app } = await import("/scripts/app.js");
      app.graph.clear();
      const node = LiteGraph.createNode("YtonEasyMediaLoader");
      node.pos = [150, 50];
      app.graph.add(node);
      app.canvas.ds.scale = 1;
      app.canvas.ds.offset = [0, 0];
      for (const name of ["image_1", "image_2"]) {
        const widget = node.widgets.find(w => w.name === name);
        widget.value = filename;
        widget.callback();
      }
      window.ytonMaskTestNode = node;
    }, filename);
    const first = target.locator('[data-slot="image_1"]');
    assert(await target.locator(".yton-mask-btn").count() === 2, "Only occupied image slots have mask actions");
    assert(await first.locator(".yton-mask-btn").evaluate(el => getComputedStyle(el).opacity) === "0", "Mask icon starts hidden");
    await first.hover();
    assert(await first.locator(".yton-mask-btn").evaluate(el => getComputedStyle(el).opacity) === "1", "Hover shows the mask icon");
    await target.mouse.move(1000, 900);
    await first.locator(".yton-mask-btn").focus();
    assert(await first.locator(".yton-mask-btn").evaluate(el => getComputedStyle(el).opacity) === "1", "Keyboard focus shows the mask icon");
    await open(2);
    await cancel();
    assert((await values())[1] === filename, "Cancel preserves the second slot");
    await open(1);
    const rect = await target.locator("#maskEditorCanvasContainer").boundingBox();
    const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
    await target.mouse.move(x - 12, y);
    await target.mouse.down();
    await target.mouse.move(x + 12, y, { steps: 6 });
    await target.mouse.up();
    await target.locator(".mask-editor-dialog button").filter({ hasText: /^\s*保存\s*$/ }).click();
    await target.locator(".mask-editor-dialog").waitFor({ state: "hidden" });
    await target.waitForFunction(original => window.ytonMaskTestNode.widgets.find(w => w.name === "image_1").value !== original, filename);
    const saved = (await values())[0];
    files.push(saved);
    assert((await values())[1] === filename, "Saving one slot leaves the other slot intact");
    const thumb = await first.locator("img").getAttribute("src");
    assert(thumb.includes(saved.split(" [")[0]), "The card previews the saved image");
    await open(1);
    const paintedPixels = await target.locator(".mask-editor-dialog canvas").nth(2).evaluate(canvas => {
      const data = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
      return Array.from(data).filter((value, index) => index % 4 === 3 && value > 0).length;
    });
    assert(paintedPixels > 0 && paintedPixels < 128 * 96, "Reopening restores the painted mask");
    await cancel();
    const workflow = await target.evaluate(() => window.comfyAPI.app.app.graph.serialize());
    assert(workflow.nodes.length === 1 && workflow.nodes[0].widgets_values[0] === saved, "Only the loader and its saved slot are serialized");
    assert(!await target.evaluate(() => Boolean(window.comfyAPI.app.ComfyApp.clipspace_return_node)), "The editor releases its temporary node");
    await target.evaluate(() => window.comfyAPI.app.app.extensionManager.setting.set("Comfy.VueNodes.Enabled", true));
    await open(2);
    await cancel();
    assert((await values())[1] === filename, "The mask action also works in the Vue node renderer");
    assert(fileChoosers === 0, "Mask actions do not open the upload picker");
    assert(errors.length === 0, errors.join("\n"));
    return { checks: ["hover/focus icon", "native editor", "cancel", "paint/save", "correct slot", "reopen mask", "workflow serialization", "Vue renderer", "no extra nodes or file chooser"], files, paintedPixels };
  } finally {
    await context.close();
  }
}
