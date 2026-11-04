"""Prepare optional video, image-batch and audio inputs for native H3 Add Guide."""

import torch

from comfy_api.latest import io


class YtonH3GuideMedia(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonH3GuideMedia", is_input_list=True, is_dev_only=True,
            inputs=[io.Video.Input("video", optional=True), io.Image.Input("image", optional=True),
                    io.Audio.Input("audio", optional=True)],
            outputs=[io.Image.Output(), io.Audio.Output()])

    @classmethod
    def execute(cls, video=None, image=None, audio=None):
        frames = next((item for item in image or [] if item is not None), None)
        soundtrack = None
        source = next((item for item in video or [] if item is not None), None)
        if source is not None:
            components = source.get_components()
            frames, soundtrack = components.images, components.audio
            fps = float(components.frame_rate)
            if fps != 24:
                count = max(1, int(len(frames) / fps * 24))
                indices = (torch.arange(count, device=frames.device) * fps / 24).long()
                frames = frames[indices.clamp_max(len(frames) - 1)]
        soundtrack = next((item for item in audio or [] if item is not None), soundtrack)
        if frames is None and soundtrack is None:
            raise ValueError("Add Guide 已开启，请连接注入视频、图片或音频。")
        return io.NodeOutput(frames, soundtrack)


NODE_CLASS_MAPPINGS = {"YtonH3GuideMedia": YtonH3GuideMedia}
NODE_DISPLAY_NAME_MAPPINGS = {"YtonH3GuideMedia": "H3 引导媒体解析"}
