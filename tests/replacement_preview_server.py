"""Isolated CPU fixture API for browser tests; does not queue ComfyUI jobs."""

import asyncio
import json
from pathlib import Path
import types

from aiohttp import web

from test_character_replacement import ReplacementTests, CLASSES, DynamicPrompt, YtonReplacementVideoSave, folder_paths, io
from replacement_test_plugin.replacement import routes
from replacement_test_plugin.replacement.media import segment_video
from replacement_test_plugin.prompt_optimizer import get_store
import server


ReplacementTests.setUpClass()
root=ReplacementTests.root
folder_paths.set_user_directory(str(root/"user"))
route_table=web.RouteTableDef()
server.PromptServer.instance=types.SimpleNamespace(routes=route_table)
routes.install()
get_store().save({"providers":[{"id":"fixture","name":"本地视觉测试","baseUrl":"http://127.0.0.1:8190/v1",
                 "apiKey":"","models":["fixture-vision"],"enabled":True}],"defaultModel":'["fixture","fixture-vision"]'})


@route_table.get("/definitions")
async def definitions(request):
    return web.json_response({cls.__name__:cls.GET_NODE_INFO_V1() for cls in CLASSES})


@route_table.get("/config")
async def config(request):
    return web.json_response(ReplacementTests().config())


@route_table.get("/saved")
async def saved(request):
    video,_=await asyncio.to_thread(segment_video,ReplacementTests().config(),0)
    node=type("ReplacementPreviewSave",(YtonReplacementVideoSave,),{})
    node.hidden=io.HiddenHolder.from_dict({io.Hidden.unique_id:"save",io.Hidden.dynprompt:DynamicPrompt({})})
    options=dict(filename_prefix="browser/video",container="mp4",fps=24,crf=18,save_full=True)
    await asyncio.to_thread(node.execute,video,1,2,**options)
    result=await asyncio.to_thread(node.execute,video,2,2,**options)
    return web.json_response(result.ui)


@route_table.get("/view")
async def view(request):
    kind=request.query.get("type","input")
    if kind not in ("input","output","temp"):
        raise web.HTTPBadRequest()
    path=(root/kind/request.query.get("subfolder","")/request.query["filename"]).resolve()
    if not path.is_relative_to(root/kind):
        raise web.HTTPForbidden()
    return web.FileResponse(path)


@route_table.post("/upload/image")
async def upload(request):
    data=await request.post()
    media=data["image"]
    filename=Path(media.filename).name
    subfolder="yton-replacement"
    dest=root/"input"/subfolder/filename
    dest.parent.mkdir(exist_ok=True)
    dest.write_bytes(media.file.read())
    return web.json_response({"name":filename,"subfolder":subfolder,"type":"input"})


@route_table.get("/v1/models")
async def models(request):
    return web.json_response({"data":[{"id":"fixture-vision"}]})


@route_table.post("/v1/chat/completions")
async def completion(request):
    data=await request.json()
    assert data["messages"][0]["role"]=="system"
    assert data["messages"][1]["content"][1]["type"]=="image_url"
    return web.json_response({"choices":[{"message":{"content":"【主体替换】将 <Video 1> 主体替换为 <Picture 1> 的角色。\n【角色外观】参考图片。\n【背景】保持原场景。\n【同步要求】动作与表情同步。\n【负面提示】重影、模糊、身份漂移。"}}]})


app=web.Application(client_max_size=32*1024**2)
app.add_routes(route_table)
web.run_app(app,host="127.0.0.1",port=8190,print=None)
