"""Share one ordered reference collection between PGS, both H3 passes and face refinement."""

import nodes
from comfy_api.latest import io
from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo


ASSETS = io.Custom("H3_REFERENCE_ASSETS")
PGS_SCHEDULE = io.Custom("H3_PGS_ASSETS")


class YtonH3ReferenceAssets(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="YtonH3ReferenceAssets",
            display_name="H3 参考素材集合",
            category="yton-nodes/MiniMax H3",
            description=("参考图按入口顺序对应 <Picture N>；人物、场景、服装等用途由提示词决定。"
                         "连接后自动增加下一个入口，未连接的参考图不参与生成。"
                         "可把 PGS 图片标记链接到“PGS 图片标记”，保留自定义别名和图片顺序。"
                         "“参考素材”连接生成与修脸；“PGS schedule”连接提示词编辑器的 assets。"),
            inputs=[
                io.Autogrow.Input("images", optional=True, display_name="参考图",
                    template=io.Autogrow.TemplateNames(
                        io.Image.Input("image"),
                        names=[f"参考图 {i}" for i in range(1, io.Autogrow._MaxNames + 1)], min=0)),
                io.Image.Input("video_frames", optional=True, display_name="源视频画面"),
                io.Audio.Input("video_audio", optional=True, display_name="源视频音频"),
                PGS_SCHEDULE.Input("pgs_images", optional=True, display_name="PGS 图片标记"),
            ],
            outputs=[ASSETS.Output(display_name="参考素材"),
                     PGS_SCHEDULE.Output(display_name="PGS schedule")],
        )

    @classmethod
    def execute(cls, images=None, video_frames=None, video_audio=None, pgs_images=None):
        marked = pgs_images or {}
        pictures = list(marked.get("images", []))
        metadata = [a for a in marked.get("assets", []) if a.get("kind") in ("picture", "image")]
        if len(pictures) != len(metadata):
            raise ValueError("PGS 图片标记未携带图片数据，请重启 ComfyUI 以加载更新后的 PGS 插件。")
        schedule = {"assets": metadata}
        ordered = sorted((images or {}).items(), key=lambda item: int(item[0].rsplit(" ", 1)[-1]))
        extra = [image for _, image in ordered if image is not None]
        if extra:
            register = nodes.NODE_CLASS_MAPPINGS["MiniMaxH3RefPGSPictureAsset"]()
            for index, image in enumerate(extra, len(pictures) + 1):
                schedule, _ = register.register(image, f"Picture_{index}", f"参考图 {index}", previous=schedule)
        pictures.extend(extra)
        if video_frames is not None:
            register = nodes.NODE_CLASS_MAPPINGS["MiniMaxH3RefPGSVideoAsset"]()
            schedule, _ = register.register(video_frames, "Video_1", "源视频", previous=schedule,
                                             audio_input=video_audio)
        references = {"images": pictures, "video_frames": video_frames, "video_audio": video_audio}
        return io.NodeOutput(references, {"assets": schedule["assets"]})


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
