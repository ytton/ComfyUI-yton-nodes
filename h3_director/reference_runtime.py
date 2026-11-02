"""Share one ordered reference collection between PGS, both H3 passes and face refinement."""

import nodes
from comfy_api.latest import io
from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo


ASSETS = io.Custom("H3_PGS_ASSETS")


class YtonH3ReferenceAssets(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="YtonH3ReferenceAssets",
            display_name="H3 参考素材集合",
            category="yton-nodes/MiniMax H3",
            description=("参考图按入口顺序对应 <Picture N>；人物、场景、服装等用途由提示词决定。"
                         "连接后自动增加下一个入口，未连接的参考图不参与生成。"
                         "素材集合同时供提示词编辑、首采、二采和修脸使用。"),
            inputs=[
                io.Autogrow.Input("images", optional=True, display_name="参考图",
                    template=io.Autogrow.TemplateNames(
                        io.Image.Input("image"),
                        names=[f"参考图 {i}" for i in range(1, io.Autogrow._MaxNames + 1)], min=0)),
                io.Image.Input("video_frames", optional=True, display_name="源视频画面"),
                io.Audio.Input("video_audio", optional=True, display_name="源视频音频"),
            ],
            outputs=[ASSETS.Output(display_name="参考素材")],
        )

    @classmethod
    def execute(cls, images=None, video_frames=None, video_audio=None):
        pictures = [image for image in (images or {}).values() if image is not None]
        schedule = {"assets": []}
        if pictures:
            register = nodes.NODE_CLASS_MAPPINGS["MiniMaxH3RefPGSPictureAsset"]()
            for index, image in enumerate(pictures, 1):
                schedule, _ = register.register(image, f"Picture_{index}", f"参考图 {index}", previous=schedule)
        if video_frames is not None:
            register = nodes.NODE_CLASS_MAPPINGS["MiniMaxH3RefPGSVideoAsset"]()
            schedule, _ = register.register(video_frames, "Video_1", "源视频", previous=schedule,
                                             audio_input=video_audio)
        schedule.update(images=pictures, video_frames=video_frames, video_audio=video_audio)
        return io.NodeOutput(schedule)


class YtonH3ReferenceFromAssets(MiniMaxH3ReferenceToVideo):
    @classmethod
    def define_schema(cls):
        schema = super().define_schema()
        schema.node_id = "YtonH3ReferenceFromAssets"
        schema.display_name = "H3 参考编码 · 素材集合"
        schema.category = "yton-nodes/MiniMax H3"
        groups = {"ref_images", "ref_videos", "ref_video_audios", "ref_audios"}
        schema.inputs = [item for item in schema.inputs if item.id not in groups]
        schema.inputs.append(ASSETS.Input("assets", optional=True, display_name="参考素材"))
        return schema

    @classmethod
    def execute(cls, clip, prompt, width, height, length, ref_image_size="match",
                vae=None, audio_vae=None, assets=None):
        assets = assets or {}
        images = {f"ref_image_{i}": image for i, image in enumerate(assets.get("images", []))}
        video, audio = assets.get("video_frames"), assets.get("video_audio")
        return MiniMaxH3ReferenceToVideo.execute(
            clip=clip, prompt=prompt, width=width, height=height, length=length,
            ref_image_size=ref_image_size, vae=vae, audio_vae=audio_vae, ref_images=images,
            ref_videos={"ref_video_0": video} if video is not None else {},
            ref_audios={"ref_audio_0": audio} if audio is not None else {},
        )


NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in (YtonH3ReferenceAssets, YtonH3ReferenceFromAssets)}
NODE_DISPLAY_NAME_MAPPINGS = {cls.__name__: cls.define_schema().display_name
                              for cls in (YtonH3ReferenceAssets, YtonH3ReferenceFromAssets)}
