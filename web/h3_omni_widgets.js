import { app } from "../../../scripts/app.js";

const sections = [
  ["生成", ["prompt", "width", "height", "mode", "duration", "ref_image_size"]],
  ["主采样", ["sampling_mode", "steps", "sampler_name", "scheduler", "denoise"]],
  ["二采方案", ["sampling_plan", "first_pass_scale", "upscale_model", "second_model", "film_method", "film_model", "second_sampler", "second_steps", "second_sigma_start", "second_rho", "second_sigma_values", "second_ff_chunks", "film_audio_denoise", "film_noise_resample", "film_match_stats", "selflift_transition_step", "selflift_rho", "selflift_w_min", "selflift_w_max", "selflift_highres_tiling", "selflift_highres_tiles"]],
  ["小脸修复", ["face_model", "face_refine", "face_count", "face_sigmas", "face_reverse"]],
  ["种子", ["seed", "control_after_generate"]],
  ["分段上下文", ["enable_context", "clip_index", "h3_context_length"]],
  ["视频解码", ["vae_decode_mode", "x2_vae_name", "vae_tile_size", "vae_tile_overlap"]],
];
const labels = {
  prompt: "提示词", width: "最终宽度", height: "最终高度", duration: "成片目标时长 / 秒",
  mode: "生成模式", sampling_mode: "采样模式",
  ref_image_size: "参考图尺寸", steps: "调度步数", sampler_name: "采样器",
  scheduler: "调度器", denoise: "调度降噪", seed: "随机种子",
  clip_index: "当前片段序号",
  enable_context: "启用上下文",
  first_pass_scale: "首采宽高比例", upscale_model: "潜空间放大模型",
  second_sampler: "二采采样器", second_sigma_values: "二采 Sigma（手填）",
  second_steps: "二采步数", second_sigma_start: "二采起始 Sigma / 重绘力度", second_rho: "去网格曲线 / rho",
  second_ff_chunks: "二采前馈分块",
  selflift_transition_step: "升分辨率切换步数", selflift_rho: "VAE 校正范围 / rho",
  selflift_w_min: "校正权重下限", selflift_w_max: "校正权重上限",
  selflift_highres_tiling: "高分辨率空间分块", selflift_highres_tiles: "空间分块数",
  sampling_plan: "二采方案", film_model: "Film 2× 模型",
  film_method: "放大方式 / method", film_audio_denoise: "音频降噪 / audio_denoise",
  film_noise_resample: "噪声重采样 / noise_resample", film_match_stats: "统计匹配 / match_stats",
  face_refine: "启用小脸修复", face_count: "修脸人数", face_reverse: "倒序修脸",
  vae_decode_mode: "VAE 解码模式", x2_vae_name: "X2 解码 VAE",
  vae_tile_size: "解码分块大小", vae_tile_overlap: "解码分块重叠",
};

function setupSections(node) {
  const plan = { YtonH3VideoContextOmniGenerate: "TR · Film 2×",
    YtonH3SelfLiftOmniGenerate: "SelfLift", YtonH3TraditionalOmniGenerate: "传统二采" }[node.comfyClass];
  const film = node.comfyClass === "YtonH3VideoContextOmniGenerate";
  const selflift = node.comfyClass === "YtonH3SelfLiftOmniGenerate";
  const widgets = new Map(node.widgets.map(widget => [widget.name, widget]));
  const socketLabels = { second_model: "二采模型（可选）", face_model: "修脸模型（可选）" };
  for (const [name, label] of Object.entries(socketLabels)) {
    const widget = node.addCustomWidget({
      name, label, type: "h3_input", value: "", serialize: false, options: { serialize: false },
      computeSize: () => [0, 24],
      computeLayoutSize: () => ({ minHeight: 24, maxHeight: 24, minWidth: 0 }),
      draw(ctx, currentNode, width, y) {
        ctx.save();
        ctx.font = "12px sans-serif";
        ctx.fillStyle = currentNode.title_text_color || LiteGraph.NODE_TEXT_COLOR;
        ctx.textAlign = "left";
        ctx.fillText(label, 14, y + 16);
        ctx.restore();
      },
    });
    widgets.set(name, widget);
  }
  const info = [["h3_context_length", "接续重叠区（固定）", 22, " 帧"],
    ["sampling_plan", "二采方式（固定）", plan, ""]];
  if (film) info.push(["first_pass_scale", "首采宽高比例（固定）", 0.5, ""]);
  for (const [name, label, value, suffix] of info) {
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
        ctx.fillText(`${value}${suffix}`, width - 14, y + 16);
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
  const secondPassWidgets = node.widgets.filter(widget =>
    widget.name === "h3_section_二采方案" || sections[2][1].includes(widget.name));
  const decodeWidgets = ["x2_vae_name", "vae_tile_size", "vae_tile_overlap"].map(name => widgets.get(name));
  const visibleLayout = new Map([...secondPassWidgets, ...decodeWidgets].map(widget => [widget, {
    type: widget.type, computeSize: widget.computeSize, computeLayoutSize: widget.computeLayoutSize,
  }]));
  let secondPassVisible = true;
  const hiddenInput = input => widgets.get(input?.widget?.name)?.hidden === true;
  const updateDisabled = node.updateComputedDisabled;
  node.updateComputedDisabled = function () {
    updateDisabled.apply(this, arguments);
    for (const widget of this.widgets) {
      if (socketLabels[widget.name]) widget.connectionSuppressed = false;
    }
  };
  const setConcreteSlots = node._setConcreteSlots;
  node._setConcreteSlots = function () {
    setConcreteSlots.apply(this, arguments);
    this._concreteInputs = this._concreteInputs.filter(input => {
      if (!hiddenInput(input)) return true;
      input.boundingRect[0] = input.boundingRect[1] = Number.NaN;
      input.boundingRect[2] = input.boundingRect[3] = 0;
      return false;
    });
  };
  const measureSlot = node._measureSlot;
  // Filter drawing slots without changing the input indices saved in links.
  node._measureSlot = function (slot, index, isInput) {
    return measureSlot.call(this, slot, isInput ? this.inputs.indexOf(slot) : index, isInput);
  };
  const connectionPos = node.getConnectionPos;
  node.getConnectionPos = function (isInput, index, out) {
    const result = connectionPos.call(this, isInput, index, out);
    if (isInput && hiddenInput(this.inputs[index])) {
      result[0] = this.pos[0];
      result[1] = this.pos[1] - LiteGraph.NODE_TITLE_HEIGHT * 0.5;
    }
    return result;
  };
  const inputPos = node.getInputPos;
  node.getInputPos = function (index) {
    return hiddenInput(this.inputs[index]) ? [Number.NaN, Number.NaN] : inputPos.call(this, index);
  };
  function showSecondPass(visible) {
    if (secondPassVisible === visible) return;
    secondPassVisible = visible;
    showControls(secondPassWidgets, visible);
  }
  function showControls(controls, visible) {
    if (controls.every(widget => Boolean(widget.hidden) === !visible)) return;
    for (const widget of controls) {
      const layout = visibleLayout.get(widget);
      widget.hidden = !visible;
      if (widget.options) widget.options.hidden = !visible;
      widget.type = visible ? layout.type : "hidden";
      widget.computeSize = visible ? layout.computeSize : () => [0, -4];
      widget.computeLayoutSize = visible ? layout.computeLayoutSize : () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
    }
    node.setSize([node.size[0], node.computeSize()[1]]);
    if (node.graph) node.arrange();
  }
  function labelSockets() {
    const inputLabels = { model_loader: "主模型", image: "图片", video: "视频", audio: "音频", previous_video: "上一段视频（可选）", sigmas: "自定义 Sigma", face_sigmas: "修脸 Sigma",
      second_model: "二采模型（可选）", face_model: "修脸模型（可选）", ...labels };
    inputLabels.sigmas = "自定义 Sigma";
    inputLabels.second_sigma_values = "二采 Sigma";
    inputLabels.face_sigmas = "修脸 Sigma";
    for (const input of node.inputs) {
      if (inputLabels[input.name]) input.label = inputLabels[input.name];
      if (socketLabels[input.name]) input.widget = { name: input.name };
    }
    for (const output of node.outputs) {
      output.label = { video: "本段视频", av_latent: "最终 AV latent" }[output.name];
    }
  }
  function syncControlState() {
    const custom = node.inputs.find(input => input.name === "sigmas")?.link != null;
    for (const name of ["steps", "scheduler", "denoise"]) {
      widgets.get(name).disabled = custom;
    }
    widgets.get("duration").disabled = widgets.get("mode").value === "复刻模式";
    const twoPass = widgets.get("sampling_mode").value === "二采";
    showSecondPass(twoPass);
    const decodeMode = widgets.get("vae_decode_mode").value;
    const x2Decode = decodeMode === "X2 VAE 解码";
    showControls([widgets.get("x2_vae_name")], x2Decode);
    showControls(decodeWidgets.slice(1), decodeMode !== "标准解码");
    widgets.get("width").label = x2Decode ? "采样画布宽度（成片 ×2）" : labels.width;
    widgets.get("height").label = x2Decode ? "采样画布高度（成片 ×2）" : labels.height;
    const scale = widgets.get("first_pass_scale");
    if (film) scale.value = 0.5;
    scale.disabled = !twoPass || film;
    scale.label = film ? "首采宽高比例（固定 0.5）" : labels.first_pass_scale;
    if (widgets.has("upscale_model")) widgets.get("upscale_model").disabled = !twoPass;
    if (widgets.has("second_sampler")) widgets.get("second_sampler").disabled = !twoPass;
    widgets.get("sampler_name").disabled = selflift && twoPass;
    const secondSigmaLinked = node.inputs.find(input => input.name === "second_sigma_values")?.link != null;
    const secondSigmaText = widgets.get("second_sigma_values");
    if (secondSigmaText) {
      secondSigmaText.disabled = !twoPass || secondSigmaLinked;
      secondSigmaText.label = secondSigmaLinked ? "二采 Sigma（已由连线提供）" : "二采 Sigma（留空自动）";
      const customSecondSigma = secondSigmaLinked || secondSigmaText.value.trim() !== "";
      for (const name of ["second_steps", "second_sigma_start", "second_rho"]) {
        widgets.get(name).disabled = !twoPass || customSecondSigma;
      }
    }
    for (const name of ["film_method", "film_model", "second_ff_chunks", "film_audio_denoise", "film_noise_resample", "film_match_stats", "selflift_transition_step", "selflift_rho", "selflift_w_min", "selflift_w_max", "selflift_highres_tiling", "selflift_highres_tiles"]) {
      if (widgets.has(name)) widgets.get(name).disabled = !twoPass;
    }
    if (film) {
      const methodLinked = node.inputs.find(input => input.name === "film_method")?.link != null;
      const learned = !methodLinked && widgets.get("film_method").value === "learned model";
      widgets.get("film_match_stats").label = learned ? "统计匹配 / match_stats（当前方式忽略）" : labels.film_match_stats;
      widgets.get("film_noise_resample").label = "噪声重采样 / noise_resample（当前插件同效）";
    }
    for (const name of ["face_count", "face_reverse"]) {
      if (widgets.has(name)) widgets.get(name).disabled = !widgets.get("face_refine").value;
    }
    widgets.get("face_sigmas").label = "修脸 Sigma";
    widgets.get("face_sigmas").disabled = !widgets.get("face_refine").value;
    node.setDirtyCanvas(true, true);
  }
  for (const name of ["mode", "sampling_mode", "face_refine", "first_pass_scale", "face_sigmas", "film_method", "second_sigma_values", "vae_decode_mode"]) {
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
    if (["YtonH3VideoContextOmniGenerate", "YtonH3SelfLiftOmniGenerate", "YtonH3TraditionalOmniGenerate"].includes(node.comfyClass)) setupSections(node);
  },
});
