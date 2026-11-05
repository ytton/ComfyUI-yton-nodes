"""UI-only media planning and LLM actions, independent of the generation queue."""

import asyncio
import logging
from pathlib import Path

import folder_paths

from aiohttp import web

from ..llm_connection import LLMConnection
from ..prompt_optimizer import discover_models, get_store
from .anchors import editor_preview, frame_preview
from .media import contact_sheet, output_size, plan_for, reference_images, segment_video
from .save import preview
from .shots import shot_plan
from .prompts import SYSTEM, load_skill, optimize, save_skill, signature


def install():
    from server import PromptServer
    server = getattr(PromptServer, "instance", None)
    if server is None:
        return
    routes = server.routes

    async def respond(operation):
        try:
            return web.json_response(await asyncio.to_thread(operation))
        except (ValueError, KeyError, TypeError, OSError) as error:
            return web.json_response({"error": str(error)}, status=400)
        except Exception:
            logging.exception("[yton] 人物替换处理失败")
            return web.json_response({"error": "处理失败，请查看 ComfyUI 日志。"}, status=500)

    @routes.get("/yton/llm/settings")
    async def settings(request):
        return await respond(lambda: get_store().public())

    @routes.post("/yton/llm/settings")
    async def save_settings(request):
        data = await request.json()
        return await respond(lambda: get_store().save(data))

    @routes.post("/yton/llm/models")
    @routes.post("/yton/llm/test")
    async def models(request):
        data = await request.json()
        def operation():
            models = discover_models(get_store().draft_provider(data))
            return {"models": models, "message": f"连接成功，已读取 {len(models)} 个模型。"}
        return await respond(operation)

    @routes.post("/yton/replacement/plan")
    async def plan(request):
        config = await request.json()
        def operation():
            metadata, result = plan_for(config)
            width, height = output_size(config, metadata)
            return {"metadata": metadata, "plan": result, "output_size": {"width": width, "height": height}}
        return await respond(operation)

    @routes.post("/yton/replacement/shot-plan")
    async def detect_shots(request):
        data = await request.json()
        return await respond(lambda: shot_plan(data["video"], data["settings"]))

    @routes.post("/yton/replacement/segment-preview")
    async def segment_preview(request):
        data = await request.json()
        def operation():
            video, _ = segment_video(data["config"], int(data["index"]))
            return {"video": preview(Path(video.get_stream_source()), "temp")}
        return await respond(operation)

    @routes.get("/yton/replacement/skill")
    async def optimization_skill(request):
        return await respond(lambda: {"skill": load_skill(), "default_skill": SYSTEM})

    @routes.post("/yton/replacement/anchor-preview")
    async def anchor_preview(request):
        data = await request.json()
        return await respond(lambda: editor_preview(data["config"], int(data["index"])))

    @routes.post("/yton/replacement/anchor-frame")
    async def anchor_frame(request):
        data = await request.json()
        return await respond(lambda: frame_preview(data["config"], int(data["index"]), data["frame"]))

    @routes.post("/yton/replacement/skill")
    async def save_optimization_skill(request):
        data = await request.json()
        return await respond(lambda: save_skill(data["skill"]))

    @routes.post("/yton/replacement/optimize")
    async def optimize_prompt(request):
        data = await request.json()
        def operation():
            connection = LLMConnection(**data["connection"])
            config, index = data["config"], int(data["index"])
            video, _ = segment_video(config, index)
            return {"text": optimize(connection, config, index, video, reference_images(config)),
                    "signature": signature(config, index)}
        return await respond(operation)

    @routes.post("/yton/replacement/frames")
    async def frames(request):
        data = await request.json()
        def operation():
            config, index = data["config"], int(data["index"])
            video, _ = segment_video(config, index)
            path = Path(folder_paths.get_temp_directory()) / "yton-replacement" / f"{signature(config, index)}-{index}-frames.jpg"
            contact_sheet(video).save(path, quality=90)
            return {"image": preview(path, "temp")}
        return await respond(operation)
