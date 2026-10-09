async (page) => {
  const context = await page.context().browser().newContext({ viewport: { width: 1440, height: 1100 }, permissions: ["clipboard-read", "clipboard-write"] });
  const target = await context.newPage();
  const errors = [];
  target.on("pageerror", error => { if (/yton|media_loader|node_panel/i.test(error.stack || "")) errors.push(error.stack || error.message); });
  target.on("console", message => { if (message.type() === "error" && /yton|media_loader|node_panel/i.test(message.text())) errors.push(message.text()); });
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const origin = "http://127.0.0.1:8192";
  const definitions = await context.request.get(`${origin}/temp/node-definitions.json`).then(response => response.json());
  await context.route("**/extensions/ComfyUI-yton-nodes/**", async route => {
    const relative = new URL(route.request().url()).pathname.split("/extensions/ComfyUI-yton-nodes/")[1];
    await route.fulfill({ response: await context.request.get(`${origin}/web/${relative}`) });
  });
  await context.route("**/object_info**", async route => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), ...definitions } });
  });
  await context.route("**/settings**", async route => {
    if (route.request().method() === "POST") await route.fulfill({ json: {} });
    else await route.continue();
  });
  const imageBuffer = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/r1sAAAAASUVORK5CYII=", "base64");
  let uploadCount = 0;
  await context.route("**/upload/image", async route => {
    uploadCount++;
    const extension = route.request().postDataBuffer()?.toString().match(/filename="[^"\r\n]+\.([^".\r\n]+)"/)?.[1] || "png";
    await route.fulfill({ json: { name: `reference-${uploadCount}.${extension}`, subfolder: "yton-media", type: "input" } });
  });
  await context.route("**/view?**", async route => {
    await route.fulfill({ contentType: "image/png", body: imageBuffer });
  });
  const checks = [];
  try {
    await target.goto("http://127.0.0.1:8188/", { waitUntil: "domcontentloaded" });
    await target.waitForFunction(() => window.LiteGraph?.registered_node_types?.YtonAudioParser);
    await target.getByRole("button", { name: "运行", exact: true }).first().waitFor();
    await target.evaluate(() => {
      const app = window.comfyAPI.app.app;
      app.graph.clear();
      const node = LiteGraph.createNode("YtonEasyMediaLoader");
      node.pos = [160, 60];
      app.graph.add(node);
      app.canvas.ds.offset = [0, 0];
      app.canvas.ds.scale = 1;
      window.ytonMediaTestNode = node;
      app.canvas.setDirty(true, true);
    });
    const panel = target.locator(".yton-media-panel");
    await panel.waitFor({ state: "visible", timeout: 8000 }).catch(error => { throw new Error(`${error.message}\n${errors.join("\n")}`); });
    await panel.locator(".image-grid").waitFor({ state: "visible" });
    assert(await panel.locator(".yton-media-item").count() === 15, "Fifteen fixed slots must exist");
    assert(await panel.locator(".image-grid").isVisible(), "Images must be expanded on new nodes");
    assert(await panel.locator(".video-grid").isHidden() && await panel.locator(".audio-grid").isHidden(), "Video and audio must be collapsed on new nodes");
    const initialSize = await target.evaluate(() => Array.from(window.ytonMediaTestNode.size));
    assert(initialSize[0] === 640, "New media nodes must start at the larger width");
    assert(await panel.locator(".image-grid .yton-media-item").count() === 9, "Images must have nine slots");
    const schema = await target.evaluate(() => ({ inputCount: window.ytonMediaTestNode.inputs?.length || 0, outputs: window.ytonMediaTestNode.outputs.map(output => ({ name: output.name, type: output.type, shape: output.shape })) }));
    assert(schema.inputCount === 0, "The loader must have no input sockets");
    assert(schema.outputs.map(output => output.name).join(",") === "image,video,audio", "The three output sockets must be fixed");
    assert(schema.outputs.map(output => output.type).join(",") === "IMAGE,VIDEO,AUDIO", "Lists must use standard media types");
    assert(schema.outputs.every(output => output.shape === 6), "List sockets must use ComfyUI's grid shape");
    const chooserPromise = target.waitForEvent("filechooser");
    await panel.locator('[data-slot="image_7"]').click();
    const chooser = await chooserPromise;
    await chooser.setFiles([{ name: "first.png", mimeType: "image/png", buffer: imageBuffer }, { name: "second.png", mimeType: "image/png", buffer: imageBuffer }]);
    await target.waitForFunction(() => window.ytonMediaTestNode.widgets.find(widget => widget.name === "image_8").value === "yton-media/reference-2.png");
    assert(await panel.locator(".yton-media-empty").count() === 13, "Uploads must keep empty slots visible");
    await panel.locator('[data-slot="image_7"]').dragTo(panel.locator('[data-slot="image_9"]'));
    await target.waitForFunction(() => window.ytonMediaTestNode.widgets.find(widget => widget.name === "image_9").value === "yton-media/reference-1.png");
    await panel.getByRole("button", { name: "移除图片 8", exact: true }).click();
    const paths = await target.evaluate(() => window.ytonMediaTestNode.widgets.filter(widget => widget.name.startsWith("image_")).map(widget => widget.value));
    assert(paths[7] === "" && paths[8] === "yton-media/reference-1.png", "Removing a file must preserve the other slot indexes");
    assert(await panel.locator(".yton-media-item").count() === 15, "Deleting must retain all fifteen slots");
    await panel.getByRole("button", { name: "参考视频 · 3", exact: true }).click();
    assert(await panel.locator(".video-grid").isVisible(), "Collapsed categories must expand when clicked");
    const saved = await target.evaluate(() => window.ytonMediaTestNode.serialize());
    assert(saved.widgets_values.length === 15, "The custom panel must not serialize as an input");
    await target.evaluate(saved => {
      const node = window.ytonMediaTestNode;
      node.widgets.find(widget => widget.name === "image_9").value = "";
      node.properties.ytonMediaCollapsed = { image: true, video: true, audio: false };
      node.configure(saved);
    }, saved);
    assert(await panel.locator('[data-slot="image_9"] img').getAttribute("src").then(url => url.includes("subfolder=yton-media")), "Restoring must preserve the uploaded subfolder and preview");
    assert(await panel.locator(".video-grid").isVisible() && await panel.locator(".audio-grid").isHidden(), "Restoring must preserve saved collapse choices");
    await panel.getByRole("button", { name: "参考视频 · 3", exact: true }).click();
    const prompt = await target.evaluate(async () => {
      const result = await window.comfyAPI.app.app.graphToPrompt();
      const node = window.ytonMediaTestNode;
      if (!result.output[node.id]) throw new Error(`Missing loader in prompt: ${JSON.stringify({ id: node.id, result })}`);
      return result.output[node.id];
    });
    assert(Object.keys(prompt.inputs).length === 15 && prompt.inputs.image_9 === "yton-media/reference-1.png", "The submitted prompt must contain all fifteen file widgets and no panel widget");
    const parsers = await target.evaluate(() => {
      const app = window.comfyAPI.app.app;
      const loader = window.ytonMediaTestNode;
      const result = [];
      for (const [kind, count, slot] of [["Image", 9, 0], ["Video", 3, 1], ["Audio", 3, 2]]) {
        const list = LiteGraph.createNode(`Yton${kind}ListParser`);
        const item = LiteGraph.createNode(`Yton${kind}Parser`);
        app.graph.add(list); app.graph.add(item);
        loader.connect(slot, list, 0); list.connect(count - 1, item, 0);
        const easy = LiteGraph.createNode(`easy split${kind === "Image" ? "Images" : kind === "Video" ? "Videos" : "Audios"}`);
        if (!easy) throw new Error(`Missing EasyMedia ${kind} parser`);
        app.graph.add(easy);
        loader.connect(slot, easy, 0);
        const savedList = list.serialize();
        list.configure(savedList);
        result.push({ kind, count: list.outputs.length, inputName: list.inputs[0].name, inputShape: list.inputs[0].shape, connected: item.inputs[0].link != null, outputs: item.outputs.map(output => output.type), names: item.outputs.map(output => output.name), easyConnected: easy.inputs[0].link != null });
      }
      return result;
    });
    assert(parsers.every(parser => parser.connected && parser.easyConnected), "Yton and EasyMedia parser chains must connect with standard input types");
    assert(parsers.every(parser => parser.inputName === parser.kind.toLowerCase() && parser.inputShape === 6), "List parser inputs must have short media names and native grid sockets after restoring");
    assert(parsers.find(parser => parser.kind === "Image").outputs.join(",") === "IMAGE,MASK" && parsers.find(parser => parser.kind === "Audio").outputs.join(",") === "AUDIO", "Image and audio parser outputs must use standard types");
    const videoParser = parsers.find(parser => parser.kind === "Video");
    assert(videoParser.outputs.join(",") === "IMAGE,INT,AUDIO,VHS_VIDEOINFO" && videoParser.names.join(",") === "图像,帧计数,音频,视频信息", "Video parsers must expose frames, frame count, audio, and VHS video information");
    const pasteFiles = async (files, editable = false) => target.evaluate(({ files, editable }) => {
      const data = new DataTransfer();
      for (const { name, type } of files) data.items.add(new File(["clipboard-test"], name, { type }));
      const event = new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true });
      const field = editable ? document.body.appendChild(document.createElement("textarea")) : document.body;
      field.dispatchEvent(event);
      if (editable) field.remove();
      return event.defaultPrevented;
    }, { files, editable });
    await target.evaluate(() => window.comfyAPI.app.app.canvas.selectNode(window.ytonMediaTestNode));
    const nodeCount = await target.evaluate(() => window.comfyAPI.app.app.graph._nodes.length);
    // Exercise a real OS clipboard image and native Ctrl+V, not only synthetic paste events.
    await target.evaluate(async () => {
      document.activeElement?.blur();
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 2;
      const image = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
      await navigator.clipboard.write([new ClipboardItem({ "image/png": image })]);
    });
    await target.keyboard.press("Control+v");
    await target.waitForFunction(() => window.ytonMediaTestNode.widgets.find(widget => widget.name === "image_1").value === "yton-media/reference-3.png");
    assert(await pasteFiles([{ name: "clip.mp4", type: "video/mp4" }, { name: "clip.wav", type: "audio/wav" }, { name: "clip.png", type: "image/png" }]), "Selected loaders must consume mixed media paste");
    await target.waitForFunction(() => window.ytonMediaTestNode.widgets.find(widget => widget.name === "audio_1").value === "yton-media/reference-6.wav");
    const pasted = await target.evaluate(() => Object.fromEntries(window.ytonMediaTestNode.widgets.map(widget => [widget.name, widget.value])));
    assert(pasted.image_1 === "yton-media/reference-3.png" && pasted.image_2 === "yton-media/reference-4.png" && pasted.image_9 === "yton-media/reference-1.png", "Clipboard images must fill empty slots without overwriting existing media");
    assert(pasted.video_1 === "yton-media/reference-5.mp4" && pasted.audio_1 === "yton-media/reference-6.wav", "Clipboard files must be assigned to their media categories");
    assert(await panel.locator(".video-grid").isVisible() && await panel.locator(".audio-grid").isVisible(), "Pasting must expand video and audio categories");
    assert(await target.evaluate(() => window.comfyAPI.app.app.graph._nodes.length) === nodeCount, "Media paste must not create stock LoadImage nodes or duplicate graph nodes");
    const beforeIgnoredPaste = await target.evaluate(() => window.ytonMediaTestNode.widgets.map(widget => widget.value));
    assert(!await pasteFiles([{ name: "editing.png", type: "image/png" }], true), "Text editing must retain its own paste behavior");
    await target.evaluate(() => window.comfyAPI.app.app.canvas.deselectAllNodes());
    await pasteFiles([{ name: "unselected.wav", type: "audio/wav" }]);
    await target.waitForTimeout(200);
    assert(JSON.stringify(await target.evaluate(() => window.ytonMediaTestNode.widgets.map(widget => widget.value))) === JSON.stringify(beforeIgnoredPaste), "Unselected loaders and text fields must not change the loader's slots");
    const afterIgnoredPaste = uploadCount;
    await target.evaluate(() => {
      const app = window.comfyAPI.app.app;
      const second = LiteGraph.createNode("YtonEasyMediaLoader");
      app.graph.add(second);
      app.canvas.selectNodes([window.ytonMediaTestNode, second]);
      window.ytonSecondLoader = second;
    });
    await pasteFiles([{ name: "second.wav", type: "audio/wav" }]);
    await target.waitForFunction(expected => window.ytonMediaTestNode.widgets.find(widget => widget.name === "audio_2").value === expected, `yton-media/reference-${afterIgnoredPaste + 1}.wav`);
    assert(await target.evaluate(() => window.ytonSecondLoader.widgets.every(widget => !widget.value)) && uploadCount === afterIgnoredPaste + 1, "Multiple selected loaders must receive a paste only once");
    await target.evaluate(() => {
      const app = window.comfyAPI.app.app;
      app.graph.remove(window.ytonSecondLoader);
      app.canvas.selectNode(window.ytonMediaTestNode);
      window.ytonMediaTestNode.widgets.find(widget => widget.name === "video_2").value = "existing-two.mp4";
      window.ytonMediaTestNode.widgets.find(widget => widget.name === "video_3").value = "existing-three.mp4";
    });
    await pasteFiles([{ name: "overflow.mp4", type: "video/mp4" }, { name: "third.wav", type: "" }]);
    await target.waitForFunction(expected => window.ytonMediaTestNode.widgets.find(widget => widget.name === "audio_3").value === expected, `yton-media/reference-${afterIgnoredPaste + 2}.wav`);
    assert(uploadCount === afterIgnoredPaste + 2, "Full categories must not upload or replace files, while other categories still upload");
    assert(await panel.locator(".yton-media-error").filter({ hasText: "最多 3 个槽位" }).count() === 1, "Full category feedback must survive mixed-media paste");
    assert(await target.evaluate(() => window.ytonMediaTestNode.widgets.find(widget => widget.name === "video_2").value) === "existing-two.mp4", "Pasting into a full category must retain existing media");
    for (const vue of [false, true]) {
      await target.evaluate(vue => window.comfyAPI.app.app.extensionManager.setting.set("Comfy.VueNodes.Enabled", vue), vue);
      for (const width of [420, 600]) {
        await target.evaluate(width => {
          const app = window.comfyAPI.app.app;
          window.ytonMediaTestNode.setSize([width, 500]);
          app.canvas.selectNode(window.ytonMediaTestNode);
          app.canvas.setDirty(true, true);
        }, width);
        await target.waitForTimeout(400);
        const dimensions = await panel.evaluate(element => {
          const vueNode = element.closest("[data-node-id]");
          const shell = element.parentElement;
          return { columns: getComputedStyle(element.querySelector(".image-grid")).gridTemplateColumns.split(" ").length,
            overflow: shell.scrollWidth > shell.clientWidth + 1 || shell.scrollHeight > shell.clientHeight + 1,
            actual: element.offsetWidth, expected: window.ytonMediaTestNode.size[0] - (vueNode ? 24 : 28) };
        });
        assert(dimensions.columns === 3 && !dimensions.overflow && Math.abs(dimensions.actual - dimensions.expected) <= 1, `Media layout must fit in ${vue ? "Vue" : "canvas"} nodes: ${JSON.stringify(dimensions)}`);
        checks.push({ vue, width, ...dimensions });
      }
    }
    await target.screenshot({ path: "E:/vibeRepo/ComfyUI-yton-nodes/temp/media-loader-preview.png" });
    await target.evaluate(() => {
      window.ytonMediaTestNode.widgets.find(widget => widget.name === "audio_1").value = "";
      window.comfyAPI.app.app.graph.remove(window.ytonMediaTestNode);
    });
    await pasteFiles([{ name: "removed.wav", type: "audio/wav" }]);
    await target.waitForTimeout(100);
    assert(await target.evaluate(() => window.ytonMediaTestNode.widgets.find(widget => widget.name === "audio_1").value) === "", "Removed loaders must not process paste events");
    assert(errors.length === 0, `Extension errors: ${errors.join(", ")}`);
    return { passed: true, initialSize, checks, parsers, promptInputs: Object.keys(prompt.inputs).length };
  } catch (error) {
    throw new Error(`${error.stack || error.message}\nExtension errors: ${errors.join("\n")}`);
  } finally {
    await context.close();
  }
}
