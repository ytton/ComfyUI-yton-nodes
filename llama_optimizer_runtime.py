"""Lazy llama.cpp loading, one-model reuse, cancellation and cleanup."""

import atexit
import gc
import logging
from pathlib import Path
import re
import threading

from .llama_optimizer_config import resolve_files, thinking_budget
from .prompt_optimizer import OptimizerError, completion_text


SAMPLING_KEYS = ("max_tokens", "temperature", "top_k", "top_p", "min_p",
                 "repeat_penalty", "frequency_penalty", "present_penalty")
LOAD_KEYS = ("n_ctx", "n_gpu_layers", "n_threads", "n_batch", "n_ubatch",
             "flash_attn", "offload_kqv", "kv_cache_type", "image_min_tokens", "image_max_tokens", "handler")


def load_model(model_path, projector, options):
    try:
        import llama_cpp
        from llama_cpp._ggml import GGMLType
        from llama_cpp.llama_chat_format import MTMDChatHandler, Qwen35ChatHandler, Qwen3VLChatHandler
    except ImportError as error:
        raise OptimizerError("未安装所需的 llama-cpp-python 多模态运行库，请使用现有 llama.cpp 节点的 Python 环境和依赖。") from error
    import comfy.model_management as management

    if options["n_gpu_layers"] != 0:
        # Ask ComfyUI to release only the space needed by this inference model.
        required = int(Path(model_path).stat().st_size * 1.2) + 2 * 1024**3
        if projector:
            required += Path(projector).stat().st_size
        management.free_memory(required, management.get_torch_device())
        management.soft_empty_cache()
    handler = None
    model = None
    try:
        if projector:
            mode = options["handler"]
            if mode == "auto":
                name = model_path.lower()
                mode = "qwen35" if re.search(r"qwen3[.\-_]?[568]", name) else "qwen3vl" if "qwen3" in name else "mtmd"
            handler_class = {"qwen35": Qwen35ChatHandler, "qwen3vl": Qwen3VLChatHandler, "mtmd": MTMDChatHandler}[mode]
            kwargs = {"enable_thinking": options["thinking"] != "off"} if mode == "qwen35" else {}
            if mode == "qwen3vl":
                kwargs["force_reasoning"] = options["thinking"] != "off"
            handler = handler_class(mmproj_path=projector, verbose=False,
                                    use_gpu=options["n_gpu_layers"] != 0,
                                    image_min_tokens=options["image_min_tokens"],
                                    image_max_tokens=options["image_max_tokens"],
                                    batch_max_tokens=max(2048, options["n_batch"]), **kwargs)
        ubatch = max(2048, options["n_ubatch"]) if projector else options["n_ubatch"]
        kv_type = getattr(GGMLType, f"GGML_TYPE_{options['kv_cache_type'].upper()}")
        model = llama_cpp.Llama(model_path=model_path, n_ctx=options["n_ctx"],
                                n_gpu_layers="all" if options["n_gpu_layers"] == -1 else options["n_gpu_layers"],
                                n_threads=options["n_threads"] or None,
                                n_batch=max(ubatch, options["n_batch"]), n_ubatch=ubatch,
                                flash_attn_type=1 if options["flash_attn"] else 0,
                                offload_kqv=options["offload_kqv"], type_k=kv_type, type_v=kv_type,
                                chat_handler=handler, verbose=False)
        if options["n_gpu_layers"] != 0 and not llama_cpp.llama_supports_gpu_offload():
            raise OptimizerError("llama.cpp 未能加载 GPU 后端，请检查该运行库对应的 CUDA 依赖并重启 ComfyUI；如需 CPU 推理，将 GPU 层数设为 0。")
        return model, handler
    except BaseException:
        if handler is not None:
            handler.close()
        if model is not None:
            model.close()
        raise


def configure_thinking(model, handler, enabled, messages):
    if handler is not None:
        handler.extra_template_arguments["enable_thinking"] = enabled
        if hasattr(handler, "enable_thinking"):
            handler.enable_thinking = enabled
        if hasattr(handler, "force_reasoning"):
            handler.force_reasoning = enabled
        if not enabled:
            return False
        prompt = handler.chat_template.render(messages=messages, add_generation_prompt=True,
                                               **handler.extra_template_arguments)
        return enabled and bool(re.search(r"<think>\s*$", prompt))
    from llama_cpp.llama_chat_format import Jinja2ChatFormatter
    template = model.metadata.get("tokenizer.chat_template")
    if not template:
        if enabled:
            raise OptimizerError("该 GGUF 没有对话模板，无法启用思考；请选择带模板的模型。")
        return False
    formatter = Jinja2ChatFormatter(
        template="{% set enable_thinking = " + ("true" if enabled else "false") + " %}" + template,
        eos_token=model.detokenize([model.token_eos()], special=True).decode("utf-8"),
        bos_token=model.detokenize([model.token_bos()], special=True).decode("utf-8"),
        stop_token_ids=[model.token_eos()])
    model.chat_handler = formatter.to_chat_handler()
    return enabled and bool(re.search(r"<think>\s*$", formatter(messages=messages).prompt))


def local_completion_text(data, reasoning_in_prompt=False):
    # Reasoning is never a downstream image/video prompt.
    choices = data.get("choices", [])
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content = message["content"]
            if reasoning_in_prompt:
                if "</think>" in content:
                    content = content.split("</think>", 1)[1]
                elif not message.get("reasoning_content"):
                    raise OptimizerError("模型思考未正常结束，请提高输出限制或关闭思考。")
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            if "<think>" in content or "</think>" in content:
                raise OptimizerError("模型思考未正常结束，请提高输出限制或关闭思考。")
            data = {**data, "choices": [{**choices[0], "message": {**message, "content": content}}]}
    return completion_text(data)


class LlamaRuntime:
    def __init__(self):
        self.lock = threading.RLock()
        self.model = None
        self.handler = None
        self.key = None

    def close(self):
        with self.lock:
            handler, model = self.handler, self.model
            self.handler = self.model = self.key = None
            try:
                if handler is not None:
                    handler.close()
            finally:
                if model is not None:
                    model.close()
            if model is not None:
                gc.collect()

    def generate(self, model_name, options, messages, *, has_media=False):
        import comfy.model_management as management
        if not any(message["role"] == "user" for message in messages):
            # Chat templates can require a user turn even when all instructions
            # are in the system prompt. Preserve the deliberately empty input.
            messages = [*messages, {"role": "user", "content": ""}]
        paths = resolve_files(model_name, options, has_media)
        key = (*paths, *(options[name] for name in LOAD_KEYS))
        with self.lock:
            stop = threading.Event()
            success = False

            def watch_interrupt():
                while not stop.wait(0.1):
                    if management.processing_interrupted():
                        if self.model is not None:
                            self.model.abort()
                        return

            watcher = threading.Thread(target=watch_interrupt, name="yton-llama-cancel", daemon=True)
            watcher.start()
            try:
                management.throw_exception_if_processing_interrupted()
                if self.key != key:
                    self.close()
                    logging.info("[yton] 加载 llama.cpp 模型：%s", model_name)
                    self.model, self.handler = load_model(*paths, options)
                    self.key = key
                management.throw_exception_if_processing_interrupted()
                reasoning_in_prompt = configure_thinking(self.model, self.handler, options["thinking"] != "off", messages)
                data = self.model.create_chat_completion(
                    messages=messages, stream=False,
                    seed=None if options["seed"] == -1 else options["seed"],
                    reasoning_budget=thinking_budget(options),
                    reasoning_start_in_prompt=reasoning_in_prompt,
                    **{name: options[name] for name in SAMPLING_KEYS})
                management.throw_exception_if_processing_interrupted()
                text = local_completion_text(data, reasoning_in_prompt)
                success = True
                return text
            except (ValueError, RuntimeError) as error:
                management.throw_exception_if_processing_interrupted()
                if isinstance(error, OptimizerError):
                    raise
                if "does not support audio" in str(error):
                    raise OptimizerError("当前模型或 mmproj 不支持音频理解；请断开音频输入，或移除参考视频的原音轨，再运行。") from error
                raise OptimizerError(f"llama.cpp 执行失败：{str(error)[:500]}") from error
            finally:
                stop.set()
                watcher.join()
                if not success or not options["keep_loaded"]:
                    self.close()


runtime = LlamaRuntime()
atexit.register(runtime.close)
