// Compare the video content described by a prompt, independent of encoding size.
export function videoPromptContent(config, duration) {
  const plan = config.plan;
  const frame = seconds => Math.floor(Number(seconds) * 24 + 0.5);
  const target = plan.enabled && plan.mode === "MiniMax H3" ? plan.frames : frame(plan.seconds);
  const end = plan.end || duration;
  return JSON.stringify([
    config.video, frame(plan.start || 0), end ? frame(Math.min(end, duration ?? end)) : null,
    plan.mode, target, plan.output,
    plan.enabled && plan.output === "完整片段" ? plan.overlap : 0,
    config.crop || [0, 0, 1, 1],
    plan.enabled ? 24 : Number(config.compression.fps),
    plan.enabled && plan.split === "shots" ? [plan.split, plan.cuts, plan.min_seconds] : null,
  ]);
}
