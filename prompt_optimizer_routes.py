"""ComfyUI routes for the prompt optimizer's shared configuration panel."""

import asyncio
import logging

from aiohttp import web

from .prompt_optimizer import OptimizerError, discover_models, get_store
from .prompt_optimizer_skill import available_skills
from .llama_optimizer_config import model_catalogue
from .native_optimizer_runtime import NATIVE_FIELDS, DEFAULT_NATIVE
from .nodes.h3_image_node import optimize_h3_image


def install():
    from server import PromptServer
    server = getattr(PromptServer, "instance", None)
    if server is None:
        return
    routes = server.routes

    async def respond(operation):
        try:
            return web.json_response(await asyncio.to_thread(operation))
        except OptimizerError as error:
            return web.json_response({"error": str(error)}, status=400)
        except Exception:
            logging.exception("[yton] 提示词优化器请求失败")
            return web.json_response({"error": "提示词优化器处理失败，请查看 ComfyUI 日志。"}, status=500)

    async def body(request):
        try:
            value = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest(text="请求内容必须为 JSON。") from None
        if not isinstance(value, dict):
            raise web.HTTPBadRequest(text="请求内容必须为对象。")
        return value

    @routes.get("/yton/prompt-optimizer/settings")
    async def read_settings(request):
        return await respond(lambda: get_store().public())

    @routes.get("/yton/prompt-optimizer/skills")
    async def skills(request):
        return await respond(lambda: {"skills": available_skills()})

    @routes.get("/yton/prompt-optimizer/llama")
    async def llama_models(request):
        return await respond(model_catalogue)

    @routes.get("/yton/prompt-optimizer/native")
    async def native_options(request):
        return web.json_response({"fields": NATIVE_FIELDS, "defaults": DEFAULT_NATIVE})

    @routes.post("/yton/prompt-optimizer/settings")
    async def save_settings(request):
        data = await body(request)
        return await respond(lambda: get_store().save(data))

    @routes.post("/yton/prompt-optimizer/models")
    async def models(request):
        data = await body(request)
        return await respond(lambda: {"models": discover_models(get_store().draft_provider(data))})

    @routes.post("/yton/prompt-optimizer/test")
    async def test(request):
        data = await body(request)
        return await respond(lambda: {"modelCount": len(discover_models(get_store().draft_provider(data))),
                                      "message": "连接成功，模型列表接口可用。"})

    @routes.post("/yton/prompt-optimizer/h3-image")
    async def h3_image(request):
        data = await body(request)
        return await respond(lambda: optimize_h3_image(data))
