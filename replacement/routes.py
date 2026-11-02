"""UI-only media planning and LLM actions, independent of the generation queue."""

import asyncio
import logging
from pathlib import Path

import folder_paths

from aiohttp import web

from ..llm_connection import LLMConnection
from ..prompt_optimizer import discover_models, get_store
from .media import contact_sheet, plan_for, reference_images, segment_video
from .save import preview
from .prompts import optimize, signature


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
            return {"metadata": metadata, "plan": result}
        return await respond(operation)

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
