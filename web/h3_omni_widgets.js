import { app } from "../../../scripts/app.js";

const sections = [
  ["生成", ["prompt", "width", "height", "duration", "ref_image_size"]],
  ["采样", ["steps", "sampler_name", "scheduler", "denoise"]],
  ["种子", ["seed", "control_after_generate"]],
  ["上下文", ["latent_path", "clip_index", "context_length", "audio_context_length", "use_refine", "join_strength", "tail_strength"]],
];
const labels = {
  prompt: "提示词", width: "宽度", height: "高度", duration: "采样时长 / 秒",
  ref_image_size: "参考图尺寸", steps: "调度步数", sampler_name: "采样器",
  scheduler: "调度器", denoise: "调度降噪", seed: "随机种子",
  latent_path: "Latent 目录", clip_index: "当前片段序号",
  context_length: "画面上下文 / 帧", audio_context_length: "音频上下文 / 帧",
  use_refine: "轻量精修 · +1步", join_strength: "接缝匹配强度", tail_strength: "Sigma 尾段强度",
};

function setupSections(node) {
  const widgets = new Map(node.widgets.map(widget => [widget.name, widget]));
  const ordered = [];
  for (const [title, names] of sections) {
    const heading = node.addCustomWidget({
      name: `h3_section_${title}`, type: "h3_section", value: "", serialize: false,
      options: { serialize: false },
      computeSize: () => [0, 30],
      computeLayoutSize: () => ({ minHeight: 30, maxHeight: 30, minWidth: 0 }),
      draw(ctx, currentNode, width, y) {
        ctx.save();
        ctx.font = "600 12px sans-serif";
        ctx.fillStyle = currentNode.title_text_color || LiteGraph.NODE_TEXT_COLOR;
        ctx.globalAlpha = 0.72;
        ctx.textAlign = "left";
        ctx.fillText(title, 14, y + 20);
        const start = 24 + ctx.measureText(title).width;
        ctx.globalAlpha = 0.16;
        ctx.strokeStyle = ctx.fillStyle;
        ctx.beginPath();
        ctx.moveTo(start, y + 16);
        ctx.lineTo(width - 14, y + 16);
        ctx.stroke();
        ctx.restore();
      },
    });
    ordered.push(heading);
    for (const name of names) {
      const widget = widgets.get(name);
      if (!widget) continue;
      if (labels[name]) widget.label = labels[name];
      ordered.push(widget);
    }
  }
  node.widgets = ordered;
  function labelSockets() {
    const inputLabels = { model_loader: "模型", image: "图片", video: "视频", audio: "音频", sigmas: "自定义 Sigma", ...labels };
    for (const input of node.inputs) if (inputLabels[input.name]) input.label = inputLabels[input.name];
    for (const output of node.outputs) {
      output.label = { video: "视频", av_latent: "AV latent", latent_path: "Latent 路径" }[output.name];
    }
  }
  function syncScheduleState() {
    const custom = node.inputs.find(input => input.name === "sigmas")?.link != null;
    for (const name of ["steps", "scheduler", "denoise"]) {
      widgets.get(name).disabled = custom;
    }
    node.setDirtyCanvas(true, true);
  }
  const connectionsChange = node.onConnectionsChange;
  node.onConnectionsChange = function () {
    const result = connectionsChange?.apply(this, arguments);
    syncScheduleState();
    return result;
  };
  const configure = node.onConfigure;
  node.onConfigure = function () {
    const result = configure?.apply(this, arguments);
    labelSockets();
    syncScheduleState();
    return result;
  };
  labelSockets();
  syncScheduleState();
  node.setSize([Math.max(node.size[0], 400), node.computeSize()[1]]);
}

app.registerExtension({
  name: "yton.H3.OmniWidgets",
  nodeCreated(node) {
    if (node.comfyClass === "YtonH3OmniGenerate") setupSections(node);
  },
});
