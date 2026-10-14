import { app } from "../../../scripts/app.js";

app.registerExtension({
  name: "yton.minimaxH3Reference",
  nodeCreated(node) {
    if (node.comfyClass !== "YtonMiniMaxH3ReferenceToVideo") return;
    const showMediaLists = () => {
      for (const input of node.inputs || []) {
        if (["image", "video", "audio"].includes(input.name)) {
          input.shape = LiteGraph.GRID_SHAPE;
        }
      }
      node.setDirtyCanvas(true, true);
    };
    const configure = node.onConfigure;
    node.onConfigure = function () {
      const result = configure?.apply(this, arguments);
      showMediaLists();
      return result;
    };
    showMediaLists();
  },
});
