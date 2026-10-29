# H3 全模态生成 · SelfLift 无缝接续

`YtonH3SelfLiftOmniGenerate` 是 `YtonH3OmniGenerate` 的独立副本。它保留原节点的图片、视频、音频入参、单采/二采、首采比例、自定义 Sigma 和小脸修复，同时把分段上下文换成 SelfLift 工作流的引导式接续。

续段时节点会自动读取上一段保存的 22 帧尾部：前 21 帧加入 0.1 的微量噪声，最后 1 帧保持原样，再通过 `MiniMaxH3AddGuide` 与上一段尾部音频一起注入当前段。它不再把上一段 latent 硬替换到当前段头部，也不使用 `H3ColorMatchSeamlessJoin` 的全局亮度校正和淡化过渡。

当前段生成并裁掉内部上下文帧后，节点使用 SelfLift 参考流同样的 `ColorTransfer(mkl_lab, target_frame, 0, 0.75)` 做显示域匹配，再保存新的 SelfLift 上下文。第 1 段不读取上下文，第 N 段自动读取第 N−1 段；不需要用户手动裁视频或计算帧数。

示例工作流：

- `examples/H3_全模态生成_单采二采_分段修脸_SelfLift.json`
- `F:/ComfyUI/ComfyUI/user/default/workflows/H3_全模态生成_单采二采_分段修脸_SelfLift.json`

SelfLift 上下文使用独立的 `yton-h3-selflift-context-v1` 文件契约，不与旧版 latent 上下文混用。
