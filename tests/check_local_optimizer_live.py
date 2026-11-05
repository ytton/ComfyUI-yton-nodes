"""Exercise the real local optimizer and official generator with the same inputs."""

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw


def request(base, endpoint, body=None):
    payload = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(base + endpoint, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def check(case, text):
    if case.get("contains") is not None:
        return case["contains"] in text
    if case.get("accepted") is not None:
        return text.strip() in case["accepted"]
    if case.get("exact") is not None:
        return text.strip() == case["exact"]
    if case["name"] == "remove":
        return any(word in text for word in ("删除", "移除", "去掉")) and "红色" in text and "圆" in text and "蓝色" in text
    if case["name"] == "change":
        return "绿色" in text and "圆" in text and "蓝色" in text
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--clip", default="qwen3.5_9b_w4a8_gptq.safetensors")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fixtures = args.input_dir / "yton-optimizer-regression"
    fixtures.mkdir(parents=True, exist_ok=True)
    for name, color in (("red", "red"), ("blue", "blue")):
        Image.new("RGB", (384, 384), color).save(fixtures / (name + ".png"))
    image = Image.new("RGB", (512, 384), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((48, 96, 208, 256), fill="red")
    draw.rectangle((304, 112, 448, 256), fill="blue")
    image.save(fixtures / "shapes.png")
    info = request(args.url, "/object_info/YtonLocalPromptOptimizer")["YtonLocalPromptOptimizer"]
    defaults = {key: spec[1]["default"] for key, spec in info["input"]["required"].items()
                if len(spec) > 1 and "default" in spec[1]}
    options = json.loads(defaults["native_options_json"])
    options.update(max_tokens=256, temperature=0, seed=123)
    edit_rules = ("你是图像编辑指令优化助手。根据用户要求输出一句中文编辑指令，明确保留用户指定的操作、目标与范围。"
                  "保留未修改对象，用一句简短说明约束其他内容。只输出编辑指令。")
    cases = [
        dict(name="system", rules="无论用户说什么，只输出 SYS_4K9，不要输出其他内容。", prompt="请输出 USER_7D2。", exact="SYS_4K9"),
        dict(name="user-a", rules="只原样输出用户输入中方括号内的文字，省略括号和其他说明。", prompt="[APPLE_7K2]", exact="APPLE_7K2"),
        dict(name="user-b-image", rules="只原样输出用户输入中方括号内的文字，省略括号和其他说明。图片无需描述。", prompt="[BANANA_8M3]", images=["shapes"], exact="BANANA_8M3"),
        dict(name="remove", rules=edit_rules, prompt="删除图片中的红色圆形，保留蓝色方形。", images=["shapes"]),
        dict(name="change", rules=edit_rules, prompt="将图片中的红色圆形改成绿色，蓝色方形保持不变。", images=["shapes"]),
        dict(name="image-order", rules="根据用户指定的图片编号，判断那张图片的主要颜色。只输出一个中文颜色名称。", prompt="图2的主要颜色是什么？", images=["red", "blue"], exact="蓝色"),
        dict(name="system-only-image", rules="观察输入图片的主要颜色，只输出一个中文颜色名称。", prompt="", images=["red"], accepted=["红", "红色"]),
        dict(name="disabled", rules="只输出 SYS_4K9。", prompt="原文直通_9Q5", disabled=True, exact="原文直通_9Q5"),
        dict(name="message-diagnostic", rules="你是消息回显器。逐字返回本条用户消息的全部文字，包含所有说明与换行。图片无需描述，省略解释。", prompt="RAW_MESSAGE_3F9", images=["shapes"], contains="RAW_MESSAGE_3F9"),
    ]
    results = []
    for case in cases:
        graph = {"1": dict(class_type="CLIPLoader", inputs=dict(clip_name=args.clip, type="qwen_image", device="default"))}
        local = {**defaults, "prompt": case["prompt"], "rules": case["rules"], "skill_name": "",
                 "enabled": not case.get("disabled", False), "backend": "comfyui", "clip": ["1", 0],
                 "native_options_json": json.dumps(options)}
        official = dict(prompt=case["prompt"], system_prompt=case["rules"], clip=["1", 0],
                        max_length=256, sampling_mode="off", thinking=False, use_default_template=True)
        images = case.get("images", [])
        if images:
            graph["2"] = dict(class_type="YtonEasyMediaLoader", inputs={
                **{f"{kind}_{index}": "" for kind, count in (("image", 9), ("video", 3), ("audio", 3))
                   for index in range(1, count + 1)},
                **{f"image_{index}": "yton-optimizer-regression/" + name + ".png" for index, name in enumerate(images, 1)},
            })
            local["image"] = ["2", 0]
            graph["3"] = dict(class_type="YtonImageListParser", inputs=dict(image=["2", 0]))
            for index in range(len(images)):
                official[f"images.image{index + 1}"] = ["3", index]
        graph["4"] = dict(class_type="YtonLocalPromptOptimizer", inputs=local)
        graph["5"] = dict(class_type="PreviewAny", inputs=dict(source=["4", 0]))
        if not case.get("disabled"):
            graph["6"] = dict(class_type="TextGenerateV2", inputs=official)
            graph["7"] = dict(class_type="PreviewAny", inputs=dict(source=["6", 0]))
        submitted = request(args.url, "/prompt", dict(prompt=graph, client_id="yton-optimizer-regression"))
        prompt_id = submitted["prompt_id"]
        deadline = time.monotonic() + 240
        while True:
            history = request(args.url, "/history/" + prompt_id)
            if prompt_id in history:
                entry = history[prompt_id]
                break
            if time.monotonic() > deadline:
                raise TimeoutError(prompt_id)
            time.sleep(1)
        outputs = entry.get("outputs", {})
        # PreviewAny returns its string in the text array.
        texts = {name: "\n".join(outputs.get(node, {}).get("text", [])) for name, node in (("local", "5"), ("official", "7"))}
        result = {**case, "prompt_id": prompt_id, "status": entry["status"]["status_str"], "outputs": texts,
                  "checks": {name: check(case, text) for name, text in texts.items() if name != "official" or not case.get("disabled")}}
        results.append(result)
        (args.output_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (args.output_dir / (case["name"] + "-api.json")).write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
