import { app } from "../../../scripts/app.js";
import { addValueControlWidget } from "../../../scripts/widgets.js";

const modes = new Set(["fixed", "increment", "decrement", "randomize"]);

function attachSeedControl(node) {
    if (!node.subgraph || !node.subgraph.name?.includes("全模态")) return;
    const seed = node.widgets?.find(widget => widget.name === "seed");
    if (!seed || node.widgets.some(widget => widget.name === "control_after_generate")) return;
    const saved = node.properties?.yuanSeedControl;
    const control = addValueControlWidget(node, seed, modes.has(saved) ? saved : "fixed");
    seed.linkedWidgets = [...(seed.linkedWidgets ?? []), control];
    const serialize = node.onSerialize;
    node.onSerialize = function (data) {
        serialize?.call(this, data);
        data.properties ??= {};
        data.properties.yuanSeedControl = control.value;
    };
    const configure = node.onConfigure;
    node.onConfigure = function (data) {
        configure?.call(this, data);
        const mode = data.properties?.yuanSeedControl;
        if (modes.has(mode)) control.value = mode;
    };
    node.setSize(node.computeSize());
}

app.registerExtension({
    name: "yton.H3.SubgraphSeedControl",
    nodeCreated(node) {
        queueMicrotask(() => attachSeedControl(node));
    },
    loadedGraphNode(node) {
        attachSeedControl(node);
    },
});

for (const node of app.rootGraph?.nodes ?? app.graph?._nodes ?? []) attachSeedControl(node);
