"""Media-loader list inputs for the official MiniMax H3 reference node."""

from comfy_api.latest import io
from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo

from .media_loader_node import YtonVideoParser


class YtonMiniMaxH3ReferenceToVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        schema = MiniMaxH3ReferenceToVideo.define_schema()
        schema.node_id = "YtonMiniMaxH3ReferenceToVideo"
        schema.display_name = "MiniMax H3 参考生成视频"
        schema.category = "yton-nodes/MiniMax H3"
        schema.description = (
            "直接接入媒体加载器的图片、视频、音频列表；其余参数和生成逻辑与官方参考生成节点一致。"
            "视频按原时长解析为 24fps 画面，自动带入原音轨。输出正向条件和 AV latent，供后续采样。"
        )
        media_inputs = {"ref_images", "ref_videos", "ref_video_audios", "ref_audios"}
        schema.inputs = [item for item in schema.inputs if item.id not in media_inputs] + [
            io.Image.Input("image", optional=True, tooltip="图片列表，按有效素材顺序对应 <Picture N>。"),
            io.Video.Input("video", optional=True, tooltip="视频列表，自动解析为 24fps 画面及原音轨，对应 <Video N>。"),
            io.Audio.Input("audio", optional=True, tooltip="音频列表；视频原音轨先占用 <Audio N> 编号，再排列独立音频。"),
        ]
        schema.is_input_list = True
        return schema

    @classmethod
    def execute(cls, clip, prompt, width, height, length, ref_image_size=None,
                vae=None, audio_vae=None, image=None, video=None, audio=None) -> io.NodeOutput:
        ref_images = {f"ref_image_{index}": item for index, item in enumerate(image or [], 1)}
        ref_videos, ref_video_audios = {}, {}
        parser = YtonVideoParser()
        for index, item in enumerate(video or [], 1):
            frames, _, soundtrack, _ = parser.parse_video(item, force_rate=24)
            ref_videos[f"ref_video_{index}"] = frames
            ref_video_audios[f"ref_video_audio_{index}"] = soundtrack
        ref_audios = {f"ref_audio_{index}": item for index, item in enumerate(audio or [], 1)}

        # ComfyUI wraps every input in a list for INPUT_IS_LIST nodes. Only
        # media inputs are consumed as lists; the official settings stay scalar.
        return MiniMaxH3ReferenceToVideo.execute(
            clip=clip[0], prompt=prompt[0], width=width[0], height=height[0], length=length[0],
            ref_image_size=ref_image_size[0] if ref_image_size else "match",
            vae=vae[0] if vae else None, audio_vae=audio_vae[0] if audio_vae else None,
            ref_images=ref_images, ref_videos=ref_videos,
            ref_video_audios=ref_video_audios, ref_audios=ref_audios,
        )
