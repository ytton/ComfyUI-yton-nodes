"""Global, server-side GPU handoff to Qwen Launcher (no workflow nodes needed)."""
import functools
import gc
import json
import logging
import os
from pathlib import Path
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid

LOG = logging.getLogger(__name__)
DEFAULTS = {"enabled": False, "baseUrl": "http://127.0.0.1:8080", "waitSeconds": 180}


def validate_config(values):
    if not isinstance(values, dict) or set(values) - DEFAULTS.keys():
        raise ValueError("未知的启动器联动设置")
    config = {**DEFAULTS, **values}
    if type(config["enabled"]) is not bool:
        raise ValueError("enabled 必须为布尔值")
    url = urllib.parse.urlsplit(config["baseUrl"])
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost", "::1")
            or url.username or url.password or url.path not in ("", "/")
            or url.query or url.fragment or not url.port):
        raise ValueError("启动器地址应为本机 HTTP 根地址，例如 http://127.0.0.1:8080")
    config["baseUrl"] = config["baseUrl"].rstrip("/")
    if type(config["waitSeconds"]) is not int or not 10 <= config["waitSeconds"] <= 1800:
        raise ValueError("等待时间应为 10–1800 秒")
    return config


class ConfigStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            try:
                return validate_config(json.loads(self.path.read_text(encoding="utf-8")))
            except FileNotFoundError:
                return dict(DEFAULTS)

    def update(self, patch):
        with self.lock:
            config = validate_config({**self.read(), **patch})
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, self.path)
            return config


class LauncherLease:
    def __init__(self, config, interrupted=lambda: False, interrupt=lambda: None):
        self.config = config
        self.id = str(uuid.uuid4())
        self.interrupted = interrupted
        self.interrupt = interrupt
        self.stop_event = threading.Event()
        self.thread = None
        self.held = False
        self.lost = None
        self.last_contact = time.monotonic()
        # A localhost request must not pass through system HTTP proxies.
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, action):
        req = urllib.request.Request(
            self.config["baseUrl"] + "/control/gpu/" + action,
            data=json.dumps({"leaseId": self.id}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self.http.open(req, timeout=5) as response:
                value = json.load(response)
        except urllib.error.HTTPError as exc:
            message = exc.read(4096).decode("utf-8", errors="replace")
            raise RuntimeError(f"启动器 GPU 联动失败（HTTP {exc.code}）：{message}") from exc
        self.last_contact = time.monotonic()
        return value

    def acquire(self):
        deadline = time.monotonic() + self.config["waitSeconds"]
        # Mark before sending: if the reply is lost, finally still releases our UUID.
        self.held = True
        while True:
            if self.interrupted():
                raise RuntimeError("等待本地模型卸载时已取消工作流")
            try:
                result = self.request("acquire")
            except (OSError, RuntimeError) as exc:
                raise RuntimeError(
                    "无法确认本地模型已卸载，工作流尚未执行。请启动新版 Qwen Launcher，"
                    "或在 yton-nodes 设置中关闭本地模型联动。" + str(exc)) from exc
            if result.get("ready") is True:
                self.thread = threading.Thread(target=self._heartbeat, daemon=True,
                                               name="yton-qwen-gpu-lease")
                self.thread.start()
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("等待本地模型卸载超时，工作流尚未执行")
            time.sleep(0.5)

    def _heartbeat(self):
        while not self.stop_event.wait(5):
            try:
                self.request("renew")
            except Exception as exc:
                LOG.warning("[yton] 启动器续期失败：%s", exc)
                # Interrupt well before the launcher's 90-second lease expires.
                if isinstance(exc, RuntimeError) or time.monotonic() - self.last_contact > 20:
                    self.lost = f"启动器 GPU 占用许可丢失：{exc}"
                    self.interrupt()
                    return

    def release(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=6)
        if self.held:
            try:
                self.request("release")
            except Exception as exc:
                LOG.warning("[yton] 无法释放启动器占用许可，将在停止续期后自动过期：%s", exc)
            self.held = False


def report_failure(executor, prompt, prompt_id, extra_data, message):
    """Return a normal failed queue item; never kill ComfyUI's worker thread."""
    executor.success = False
    executor.history_result = {"outputs": {}, "meta": {}}
    executor.status_messages = []
    executor.server.client_id = extra_data.get("client_id")
    executor.add_message("execution_start", {"prompt_id": prompt_id}, broadcast=False)
    node_id = next(iter(prompt), "")
    executor.add_message("execution_error", {
        "prompt_id": prompt_id, "node_id": node_id,
        "node_type": prompt.get(node_id, {}).get("class_type", "YtonLauncherGuard"),
        "executed": [], "exception_message": message,
        "exception_type": "YtonLauncherGuardError", "traceback": [],
        "current_inputs": {}, "current_outputs": [],
    }, broadcast=False)
    LOG.error("[yton] %s", message)


def wrap_executor(executor_class, store, model_management, interrupt_reset):
    original = executor_class.execute
    if getattr(original, "_yton_launcher_guard", False) is True:
        return

    @functools.wraps(original)
    def execute(executor, prompt, prompt_id, extra_data=None, execute_outputs=None):
        extra_data = extra_data or {}
        execute_outputs = execute_outputs or []
        try:
            config = store.read()
        except Exception as exc:
            report_failure(executor, prompt, prompt_id, extra_data, f"启动器联动设置损坏：{exc}")
            return
        if not config["enabled"]:
            return original(executor, prompt, prompt_id, extra_data, execute_outputs)

        interrupt_reset(False)
        lease = LauncherLease(config, model_management.processing_interrupted,
                              lambda: interrupt_reset(True))
        try:
            LOG.info("[yton] 等待本地模型卸载，再执行工作流 %s", prompt_id)
            lease.acquire()
        except Exception as exc:
            lease.release()
            report_failure(executor, prompt, prompt_id, extra_data, str(exc))
            return
        try:
            return original(executor, prompt, prompt_id, extra_data, execute_outputs)
        finally:
            # ComfyUI normally retains model weights/cache. Clear these BEFORE allowing
            # the LLM to wake again, including failed/interrupted workflows.
            try:
                model_management.unload_all_models()
                gc.collect()
                model_management.soft_empty_cache()
                if lease.lost:
                    executor.success = False
                    LOG.error("[yton] %s", lease.lost)
            except Exception:
                executor.success = False
                LOG.error("[yton] 工作流结束后释放 ComfyUI 显存失败：%s", traceback.format_exc())
            finally:
                lease.release()

    execute._yton_launcher_guard = True
    executor_class.execute = execute


def install():
    import execution
    import folder_paths
    import comfy.model_management as model_management
    import nodes
    from aiohttp import web
    from server import PromptServer

    server = getattr(PromptServer, "instance", None)
    if server is None or getattr(server, "_yton_launcher_guard_routes", False):
        return
    store = ConfigStore(Path(folder_paths.get_user_directory()) / "yton-launcher.json")
    wrap_executor(execution.PromptExecutor, store, model_management, nodes.interrupt_processing)
    server._yton_launcher_guard_routes = True

    @server.routes.get("/yton/launcher-guard")
    async def get_config(request):
        try:
            return web.json_response(store.read())
        except (ValueError, OSError) as exc:
            return web.json_response({"error": str(exc)}, status=500)

    @server.routes.post("/yton/launcher-guard")
    async def set_config(request):
        try:
            patch = await request.json()
            if not isinstance(patch, dict):
                raise ValueError("设置应为 JSON 对象")
            return web.json_response(store.update(patch))
        except (ValueError, TypeError, OSError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
