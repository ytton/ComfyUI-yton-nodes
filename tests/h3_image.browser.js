async (page) => {
  const context = await page.context().browser().newContext({ viewport: { width: 1280, height: 900 } });
  const target = await context.newPage();
  const origin = "http://127.0.0.1:8192";
  const definitions = await context.request.get(`${origin}/temp/node-definitions.json`).then(response => response.json());
  const errors = [];
  target.on("pageerror", error => errors.push(error.message));
  const json = value => `return new Response(JSON.stringify(${JSON.stringify(value)}), { status: 200, headers: { "Content-Type": "application/json" } });`;
  const image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/r1sAAAAASUVORK5CYII=";

  await context.route("**/scripts/app.js", route => route.fulfill({ contentType: "text/javascript", body: `
    const extensions = [];
    export const app = {
      extensions, registerExtension(value) { extensions.push(value); },
      canvas: { graph: null, selected_nodes: {}, setDirty() {} },
    };
    window.h3TestApp = app;
  ` }));
  await context.route("**/scripts/api.js", route => route.fulfill({ contentType: "text/javascript", body: `
    export const api = {
      apiURL() { return ${JSON.stringify(image)}; },
      async fetchApi(path) {
        if (path.endsWith("/settings")) { ${json({ providers: [{ id: "test", name: "测试 LLM", enabled: true, models: ["vision"] }], defaultModel: JSON.stringify(["test", "vision"]) })} }
        if (path.endsWith("/skills")) { ${json({ skills: ["h3-image"] })} }
        if (path.endsWith("/h3-image")) { ${json({ text: "产品海报，主体参考图 1，背景使用柔和侧光。" })} }
        if (path === "/upload/image") { ${json({ name: "upload.png", subfolder: "yton-media" })} }
        throw new Error("Unexpected request: " + path);
      },
    };
  ` }));
  await context.route("**/web/js/node_panel.js", route => route.fulfill({ contentType: "text/javascript", body: `
    export function mountNodePanel(node, name, panel) {
      const shell = document.createElement("div");
      shell.append(panel);
      document.querySelector(".preview").append(shell);
      return node.addDOMWidget(name, "custom_ui", shell);
    }
  ` }));
  await context.route("**/web/js/media_mask_editor.js", route => route.fulfill({ contentType: "text/javascript", body: "export async function editSlotMask() {}" }));
  await context.route("**/web/js/media_image_preview.js", route => route.fulfill({ contentType: "text/javascript", body: "export function openImagePreview() { return () => {}; }" }));
  await context.route("**/web/js/media_mask_preview.js", route => route.fulfill({ contentType: "text/javascript", body: "export const imageChannelURL = url => url; export function showMaskPreview() {}" }));
  await context.route("**/web/js/prompt_optimizer_settings.js", route => route.fulfill({ contentType: "text/javascript", body: "export function openOptimizerSettings() {}" }));

  try {
    await target.goto(`${origin}/`, { waitUntil: "domcontentloaded" });
    await target.setContent(`<link rel="stylesheet" href="${origin}/web/css/yton_nodes.css"><div class="preview"></div><style>body{margin:0;padding:20px;background:#101418;color:#e7edf2;font-family:system-ui}.preview{width:980px;max-width:100%;margin:auto}</style>`);
    await target.evaluate(async definition => {
      const { app } = await import("/scripts/app.js");
      await import("/web/js/h3_image.js");
      const widgets = Object.entries({ ...definition.input.required, ...definition.input.optional }).map(([name, specification]) => ({
        name, value: specification[1]?.default ?? "", callback() {},
      }));
      const graph = { beforeChange() {}, afterChange() {} };
      const node = {
        comfyClass: "YtonH3ImageConfig", properties: {}, widgets, graph, inputs: [], size: [980, 600],
        setSize(size) { this.size = size; }, setDirtyCanvas() {}, addDOMWidget(name, type, element) { return { name, type, element }; },
      };
      widgets.find(widget => widget.name === "image_1").value = "yton-media/first.png";
      app.canvas.graph = graph;
      app.extensions.find(extension => extension.name === "yton.h3_image").nodeCreated(node);
      window.h3TestNode = node;
    }, definitions.YtonH3ImageConfig);

    const panel = target.locator(".yton-h3-image-panel");
    await panel.waitFor();
    await target.waitForFunction(() => getComputedStyle(document.querySelector(".yton-h3-image-panel")).display === "grid");
    if (await panel.locator(".yton-media-item").count() !== 16) throw new Error("Expected sixteen image slots");
    if (await panel.locator(".yton-h3-ratio-shape").count() !== 8) throw new Error("Expected eight aspect-ratio previews");
    const layout = await panel.evaluate(element => {
      const left = element.querySelector(".yton-h3-media-column").getBoundingClientRect();
      const right = element.querySelector(".yton-h3-controls-column").getBoundingClientRect();
      const grid = element.querySelector(".yton-media-grid");
      return { sideBySide: right.left >= left.right - 1, columns: getComputedStyle(grid).gridTemplateColumns.split(" ").length };
    });
    if (!layout.sideBySide || layout.columns !== 4) throw new Error("Two-column layout or 4x4 grid failed");

    await panel.locator('.yton-h3-ratio[data-ratio="3:2"]').click();
    if (!await panel.locator('.yton-h3-resolution[data-mp="10"] .yton-h3-k').innerText().then(value => value === "3.9K"))
      throw new Error("10 MP at 3:2 should show 3.9K");
    const custom = panel.getByRole("spinbutton", { name: "自定义分辨率，单位 MP" });
    await custom.fill("15.5");
    if (!await panel.locator(".yton-h3-custom.is-selected").count()) throw new Error("Custom resolution is not selected");
    if (!await panel.locator(".yton-h3-heading .yton-h3-detail").first().innerText().then(value => value.includes("15.5 MP")))
      throw new Error("Custom MP was not applied");
    if (await panel.getByRole("combobox", { name: "参考图缩放" }).inputValue() !== "4")
      throw new Error("Reference upscale should default to 4 MP");

    const prompt = panel.getByRole("textbox", { name: "提示词输入框" });
    await prompt.fill("参考 @");
    await panel.getByRole("option", { name: /@1/ }).click();
    if (!await prompt.inputValue().then(value => value.includes("@1"))) throw new Error("Reference mention was not inserted");
    await panel.getByRole("button", { name: "优化 Skill 与 LLM 设置" }).click();
    if (await panel.getByRole("combobox", { name: "提示词优化 Skill" }).inputValue() !== "h3-image")
      throw new Error("H3 Image skill was not selected");
    await panel.getByRole("button", { name: "优化", exact: true }).click();
    await target.waitForFunction(() => document.querySelector('textarea[aria-label="优化提示词输入框"]')?.value.includes("产品海报"));
    if (await panel.getByRole("tab", { name: "优化提示词" }).getAttribute("aria-selected") !== "true")
      throw new Error("Optimizer did not switch to result tab");

    await panel.getByRole("button", { name: "优化 Skill 与 LLM 设置" }).click();
    await target.screenshot({ path: "E:/vibeRepo/ComfyUI-yton-nodes/temp/h3-image-desktop.png", fullPage: true });
    await target.evaluate(() => { document.querySelector(".preview").style.width = "760px"; });
    const compact = await panel.evaluate(element => ({ width: element.getBoundingClientRect().width, overflow: element.scrollWidth > element.clientWidth + 1 }));
    await target.screenshot({ path: "E:/vibeRepo/ComfyUI-yton-nodes/temp/h3-image-compact.png", fullPage: true });
    if (compact.overflow) throw new Error("Node content overflows at 760px");
    if (errors.length) throw new Error(errors.join("\n"));
    return { slots: 16, columns: layout.columns, resolution: "10 MP / 3:2 = 3.9K", customMP: "15.5", referenceMinimumMP: 4, compact };
  } finally {
    await context.close();
  }
}
