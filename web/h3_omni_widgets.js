import { app } from "../../../scripts/app.js";

const sections = [
  ["生成", ["prompt", "width", "height", "mode", "duration", "ref_image_size"]],
  ["主采样", ["sampling_mode", "steps", "sampler_name", "scheduler", "denoise"]],
  ["二采方案", ["sampling_plan", "first_pass_scale", "upscale_model", "film_model", "second_sampler", "second_sigma_values",
    "selflift_transition_step", "selflift_rho", "selflift_highres_tiling"]],
  ["小脸修复", ["face_refine", "face_count", "face_steps", "face_denoise", "face_large_strength", "face_detector", "face_fallback_detector", "face_seed", "face_reverse"]],
  ["种子", ["seed", "control_after_generate"]],
  ["分段上下文", ["enable_context", "latent_path", "clip_index", "context_path", "h3_context_length"]],
];
const labels = {
  prompt: "提示词", width: "最终宽度", height: "最终高度", duration: "成片目标时长 / 秒",
  mode: "生成模式", sampling_mode: "采样模式",
  ref_image_size: "参考图尺寸", steps: "调度步数", sampler_name: "采样器",
  scheduler: "调度器", denoise: "调度降噪", seed: "随机种子",
  latent_path: "上下文保存目录", clip_index: "当前片段序号", context_path: "指定上一段上下文",
  enable_context: "启用上下文",
  first_pass_scale: "首采宽高比例", upscale_model: "潜空间放大模型",
  second_sampler: "二采采样器", second_sigma_values: "二采 Sigma",
  sampling_plan: "二采方案", film_model: "Film 2× 模型",
  selflift_transition_step: "SelfLift 低分步数", selflift_rho: "SelfLift VAE 校正比例",
  selflift_highres_tiling: "SelfLift 高分空间分块",
  face_refine: "启用小脸修复", face_count: "修脸人数", face_steps: "修脸步数",
  face_denoise: "小脸降噪强度", face_detector: "人脸检测模型", face_reverse: "倒序修脸",
  face_large_strength: "大脸降噪倍率", face_fallback_detector: "人体兜底检测", face_seed: "修脸种子",
};

function setupSections(node) {
  const widgets = new Map(node.widgets.map(widget => [widget.name, widget]));
  for (const [name, label, value] of [
    ["h3_context_length", "接续重叠区（固定）", 22],
  ]) {
    widgets.set(name, node.addCustomWidget({
      name, type: "h3_context_info", value, disabled: true, serialize: false,
      options: { serialize: false },
      computeSize: () => [0, 24],
      computeLayoutSize: () => ({ minHeight: 24, maxHeight: 24, minWidth: 0 }),
      draw(ctx, currentNode, width, y) {
        ctx.save();
        ctx.font = "12px sans-serif";
        ctx.fillStyle = currentNode.title_text_color || LiteGraph.NODE_TEXT_COLOR;
        ctx.textAlign = "left";
        ctx.fillText(label, 14, y + 16);
        ctx.textAlign = "right";
        ctx.fillText(`${value} 帧`, width - 14, y + 16);
        ctx.restore();
      },
    }));
  }
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
    const inputLabels = { model_loader: "主模型", image: "图片", video: "视频", audio: "音频", previous_video: "上一段视频（可选）", sigmas: "主采样 Sigma",
      second_sigmas: "二采 Sigma", face_sigmas: "修脸 Sigma",
      second_model: "二采模型（可选）", face_model: "修脸模型（可选）", ...labels };
    for (const input of node.inputs) if (inputLabels[input.name]) input.label = inputLabels[input.name];
    for (const output of node.outputs) {
      output.label = { video: "本段视频", av_latent: "最终 AV latent", latent_path: "本段上下文路径" }[output.name];
    }
  }
  let manualScale = widgets.get("first_pass_scale").value;
  let manualSampler = widgets.get("sampler_name").value;
  let wasFilm = false;
  let wasSelfLift = false;
  function syncControlState() {
    const custom = node.inputs.find(input => input.name === "sigmas")?.link != null;
    for (const name of ["steps", "scheduler", "denoise"]) {
      widgets.get(name).disabled = custom;
    }
    widgets.get("duration").disabled = widgets.get("mode").value === "复刻模式";
    const twoPass = widgets.get("sampling_mode").value === "二采";
    const plan = widgets.get("sampling_plan")?.value;
    const film = twoPass && plan === "Film 2×";
    const selfLift = twoPass && plan === "SelfLift Progressive Sampler (MiniMax H3)";
    const scale = widgets.get("first_pass_scale");
    if (film && !wasFilm) manualScale = scale.value;
    if (film) scale.value = 0.5;
    else if (wasFilm) scale.value = manualScale;
    scale.disabled = !twoPass || film;
    scale.label = film ? "首采宽高比例（固定 0.5）" : labels.first_pass_scale;
    if (selfLift && !wasSelfLift) manualSampler = widgets.get("sampler_name").value;
    if (selfLift) widgets.get("sampler_name").value = "euler";
    else if (wasSelfLift) widgets.get("sampler_name").value = manualSampler;
    widgets.get("sampler_name").disabled = selfLift;
    wasFilm = film;
    wasSelfLift = selfLift;
    if (widgets.has("sampling_plan")) widgets.get("sampling_plan").disabled = !twoPass;
    widgets.get("upscale_model").disabled = !twoPass || film;
    widgets.get("second_sampler").disabled = !twoPass || selfLift;
    widgets.get("second_sigma_values").disabled = !twoPass || selfLift || node.inputs.find(input => input.name === "second_sigmas")?.link != null;
    if (widgets.has("film_model")) widgets.get("film_model").disabled = !film;
    for (const name of ["selflift_transition_step", "selflift_rho", "selflift_highres_tiling"]) {
      if (widgets.has(name)) widgets.get(name).disabled = !selfLift;
    }
    for (const name of ["face_count", "face_steps", "face_denoise", "face_large_strength", "face_detector", "face_fallback_detector", "face_seed", "face_reverse"]) {
      widgets.get(name).disabled = !widgets.get("face_refine").value;
    }
    if (node.inputs.find(input => input.name === "face_sigmas")?.link != null) {
      widgets.get("face_steps").disabled = true;
      widgets.get("face_denoise").disabled = true;
    }
    node.setDirtyCanvas(true, true);
  }
  for (const name of ["mode", "sampling_mode", "sampling_plan", "face_refine", "first_pass_scale", "sampler_name"]) {
    const widget = widgets.get(name);
    if (!widget) continue;
    const callback = widget.callback;
    widget.callback = function () {
      const result = callback?.apply(this, arguments);
      syncControlState();
      return result;
    };
  }
  const connectionsChange = node.onConnectionsChange;
  node.onConnectionsChange = function () {
    const result = connectionsChange?.apply(this, arguments);
    syncControlState();
    return result;
  };
  const configure = node.onConfigure;
  node.onConfigure = function () {
    const result = configure?.apply(this, arguments);
    labelSockets();
    syncControlState();
    return result;
  };
  labelSockets();
  syncControlState();
  node.setSize([Math.max(node.size[0], 460), node.computeSize()[1]]);
}

app.registerExtension({
  name: "yton.H3.OmniWidgets",
  nodeCreated(node) {
    if (node.comfyClass === "YtonH3OmniGenerate" || node.comfyClass === "YtonH3VideoContextOmniGenerate") setupSections(node);
  },
});
