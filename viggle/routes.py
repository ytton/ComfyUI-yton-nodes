"""Editor requests stay independent from the generation queue."""

import asyncio
import hashlib
import logging
from pathlib import Path

from aiohttp import web
from comfy_api.latest import InputImpl
import folder_paths

from ..llm_connection import LLMConnection
from ..replacement.media import contact_sheet, input_path, output_size
from ..replacement.save import preview
from .media import parse_config, plan_for, preview_segment, previous_frame, references, segment, source_frame
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
            logging.exception("[yton] Viggle 处理失败")
            return web.json_response({"error": "处理失败，请查看 ComfyUI 日志。"}, status=500)

    @routes.post("/yton/viggle/plan")
    async def plan(request):
        config = parse_config(await request.json())
        def operation():
            metadata, value = plan_for(config)
            width, height = output_size(config, metadata)
            return {"metadata": metadata, "plan": value, "output_size": {"width": width, "height": height}}
        return await respond(operation)

    @routes.post("/yton/viggle/preview")
    async def video_preview(request):
        data = await request.json()
        return await respond(lambda: preview_segment(parse_config(data["config"]), int(data["index"])))

    @routes.post("/yton/viggle/frame")
    async def frame(request):
        data = await request.json()
        return await respond(lambda: source_frame(parse_config(data["config"]), int(data["index"]), data["frame"]))

    @routes.post("/yton/viggle/overlap-frame")
    async def overlap_frame(request):
        data = await request.json()
        def operation():
            file = data["previous"]
            if file["type"] != "output":
                raise ValueError("上一段需要使用已保存的生成结果。")
            name = "/".join(filter(None, [file.get("subfolder"), file["filename"]])) + " [output]"
            path = input_path(name)
            video = InputImpl.VideoFromFile(str(path))
            image, offset = previous_frame(parse_config(data["config"]), int(data["index"]), data["frame"], video)
            digest = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}:{offset}".encode()).hexdigest()
            target = Path(folder_paths.get_temp_directory()) / "yton-viggle" / f"{digest}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target)
            return {"image": preview(target, "temp"), "previous_frame": offset}
        return await respond(operation)

    @routes.post("/yton/viggle/optimize")
    async def optimize_prompt(request):
        data = await request.json()
        def operation():
            config, index = parse_config(data["config"]), int(data["index"])
            video, _ = segment(config, index)
            images, pins = references(config, index)
            text = optimize(LLMConnection(**data["connection"]), config, index, video, images, pins)
            return {"text": text, "signature": signature(config, index)}
        return await respond(operation)

    @routes.post("/yton/viggle/frames")
    async def frames(request):
        data = await request.json()
        def operation():
            config, index = parse_config(data["config"]), int(data["index"])
            video, _ = segment(config, index)
            path = Path(video.get_stream_source()).with_suffix(".sheet.jpg")
            contact_sheet(video).save(path, quality=90)
            return {"image": preview(path, "temp")}
        return await respond(operation)

    @routes.get("/yton/viggle/skill")
    async def skill(request):
        return await respond(lambda: {"skill": load_skill(), "default_skill": SYSTEM})

    @routes.post("/yton/viggle/skill")
    async def write_skill(request):
        data = await request.json()
        return await respond(lambda: save_skill(data["skill"]))
