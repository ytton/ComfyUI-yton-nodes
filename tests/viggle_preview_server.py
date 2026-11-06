"""Real Viggle CPU routes for browser checks, separate from the running queue."""

from copy import deepcopy
import types

from aiohttp import web
import test_character_replacement as fixture
from replacement_test_plugin.viggle import routes
from replacement_test_plugin.viggle.media import DEFAULT_CONFIG
from replacement_test_plugin.viggle.nodes import CLASSES
from replacement_test_plugin.replacement.media import encode
from replacement_test_plugin.replacement.nodes import YtonReplacementVideoSave
import server


fixture.ReplacementTests.setUpClass()
root=fixture.ReplacementTests.root
fixture.folder_paths.set_user_directory(str(root/"user"))
table=web.RouteTableDef()
server.PromptServer.instance=types.SimpleNamespace(routes=table)
routes.install()


@table.get("/definitions")
async def definitions(request):
    return web.json_response({cls.__name__:cls.GET_NODE_INFO_V1() for cls in [*CLASSES,YtonReplacementVideoSave]})


@table.get("/config")
async def config(request):
    result=deepcopy(DEFAULT_CONFIG)
    result.update(video="source.mp4",images=["red.png","","blue.png",""],resolution="320p")
    result["plan"].update(seconds=1.5)
    return web.json_response(result)


@table.get("/view")
async def view(request):
    kind=request.query.get("type","input")
    if kind not in ("input","output","temp"):
        raise web.HTTPBadRequest()
    path=(root/kind/request.query.get("subfolder","")/request.query["filename"]).resolve()
    if not path.is_relative_to(root/kind):
        raise web.HTTPForbidden()
    return web.FileResponse(path)


@table.post("/upload/image")
async def upload(request):
    data=await request.post();media=data["image"]
    filename=fixture.Path(media.filename).name
    dest=root/"input"/"yton-viggle"/filename
    dest.parent.mkdir(exist_ok=True);dest.write_bytes(media.file.read())
    return web.json_response({"name":filename,"subfolder":"yton-viggle","type":"input"})


@table.get("/previous")
async def previous(request):
    dest=root/"output"/"segment_0001.mp4"
    if not dest.exists():
        encode(["-i",root/"input"/"source.mp4","-frames:v",36,"-an","-c:v","libx264",dest])
    return web.json_response({"filename":dest.name,"subfolder":"","type":"output"})


application=web.Application(client_max_size=32*1024**2)
application.add_routes(table)
web.run_app(application,host="127.0.0.1",port=8191,print=None)
