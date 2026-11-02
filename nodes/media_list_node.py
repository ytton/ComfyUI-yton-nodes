"""Build native media lists without loading or decoding video and audio."""

from comfy_api.latest import io


class YtonImageToList(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="YtonImageToList", display_name="图片转列表", category="yton-nodes/媒体",
            description="按接口顺序收集图片；图片批次会逐张拆开。连接后自动增加下一个入口。",
            is_input_list=True,
            inputs=[io.Autogrow.Input("images", template=io.Autogrow.TemplatePrefix(
                io.Image.Input("image"), prefix="image_", min=1, max=100,
            ))],
            outputs=[io.Image.Output(display_name="图片列表", is_output_list=True)],
        )

    @classmethod
    def execute(cls, images):
        return io.NodeOutput([
            batch[i:i + 1]
            for name in sorted(images, key=lambda name: int(name.rsplit("_", 1)[1]))
            for batch in images[name] for i in range(batch.shape[0])
        ])


class YtonVideoToList(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="YtonVideoToList", display_name="视频转列表", category="yton-nodes/媒体",
            description="按接口顺序收集视频，保留每个视频的帧与音频，不进行拼接或解码。连接后自动增加下一个入口。",
            is_input_list=True,
            inputs=[io.Autogrow.Input("videos", template=io.Autogrow.TemplatePrefix(
                io.Video.Input("video"), prefix="video_", min=1, max=100,
            ))],
            outputs=[io.Video.Output(display_name="视频列表", is_output_list=True)],
        )

    @classmethod
    def execute(cls, videos):
        return io.NodeOutput([
            video for name in sorted(videos, key=lambda name: int(name.rsplit("_", 1)[1]))
            for video in videos[name]
        ])


class YtonAudioToList(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="YtonAudioToList", display_name="音频转列表", category="yton-nodes/媒体",
            description="按接口顺序收集音频，保留每段音频的波形与采样率，不进行混音。连接后自动增加下一个入口。",
            is_input_list=True,
            inputs=[io.Autogrow.Input("audios", template=io.Autogrow.TemplatePrefix(
                io.Audio.Input("audio"), prefix="audio_", min=1, max=100,
            ))],
            outputs=[io.Audio.Output(display_name="音频列表", is_output_list=True)],
        )

    @classmethod
    def execute(cls, audios):
        return io.NodeOutput([
            audio for name in sorted(audios, key=lambda name: int(name.rsplit("_", 1)[1]))
            for audio in audios[name]
        ])


CLASSES = [YtonImageToList, YtonVideoToList, YtonAudioToList]
