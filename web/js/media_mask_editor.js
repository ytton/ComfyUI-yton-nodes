import { app, ComfyApp } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

let editing = false;

// An isolated graph gives the native editor a writable image widget without
// adding preview nodes or widgets to the user's workflow.
export async function editSlotMask(filename, onSave) {
  if (editing || document.querySelector(".mask-editor-dialog")) return;
  editing = true;
  try {
    const clean = filename.replace(/\s*\[(input|output|temp)\]$/, "").replaceAll("\\", "/");
    const slash = clean.lastIndexOf("/");
    const image = {
      filename: clean.slice(slash + 1),
      subfolder: clean.slice(0, Math.max(0, slash)),
      type: filename.match(/\[(input|output|temp)\]$/)?.[1] || "input",
    };
    const preview = new Image();
    preview.src = api.apiURL(`/view?${new URLSearchParams(image)}`);
    await preview.decode();
    const editorNode = LiteGraph.createNode("LoadImage");
    const editorGraph = new LiteGraph.LGraph();
    editorGraph.add(editorNode);
    const widget = editorNode.widgets.find(widget => widget.name === "image");
    widget.value = filename;
    editorNode.imgs = [preview];
    editorNode.images = [image];
    const previousReturnNode = ComfyApp.clipspace_return_node;
    ComfyApp.clipspace_return_node = editorNode;

    await new Promise((resolve, reject) => {
      let opened = false;
      const dispose = () => {
        observer.disconnect();
        if (ComfyApp.clipspace_return_node === editorNode) ComfyApp.clipspace_return_node = previousReturnNode;
        editorGraph.remove(editorNode);
      };
      const observer = new MutationObserver(() => {
        const dialog = document.querySelector(".mask-editor-dialog");
        const visible = Boolean(dialog && dialog.getClientRects().length);
        if (visible) opened = true;
        if (!opened || visible) return;
        const saved = widget.value;
        dispose();
        try {
          if (saved !== filename) onSave(saved);
          app.canvas.setDirty(true, true);
          resolve();
        } catch (error) {
          reject(error);
        }
      });
      observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["style", "class"] });
      try {
        ComfyApp.open_maskeditor();
      } catch (error) {
        dispose();
        reject(error);
      }
    });
  } finally {
    editing = false;
  }
}
