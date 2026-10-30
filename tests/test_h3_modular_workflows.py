"""Offline checks of the shipped native subgraphs, including lazy branch reachability.

No ComfyUI server, model, torch installation or generation queue is required.
"""

import importlib.util
import math
from pathlib import Path
import unittest
import json

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("h3_modular_spec", ROOT / "tools/build_h3_modular_spec.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def flatten(workflow):
    """Resolve native subgraph IO to original node keys, including promoted controls."""
    definitions = {s["id"]: s for s in workflow["definitions"]["subgraphs"]}
    result = {}

    class Scope:
        def __init__(self, graph, parent=None, host=None):
            self.graph, self.parent, self.host = graph, parent, host
            self.nodes = {n["id"]: n for n in graph["nodes"]}
            self.links = {link[0] if isinstance(link, list) else link["id"]: link for link in graph["links"]}

        def resolve_link(self, link_id):
            link = self.links[link_id]
            if isinstance(link, list):
                return self.resolve(link[1], link[2])
            return self.resolve(link["origin_id"], link["origin_slot"])

        def resolve(self, node_id, slot):
            if node_id == -10:
                port = self.host["inputs"][slot]
                if port["link"] is not None:
                    return self.parent.resolve_link(port["link"])
                widget_names = [p["name"] for p in self.host["inputs"] if p.get("widget")]
                return self.host["widgets_values"][widget_names.index(port["name"])]
            node = self.nodes[node_id]
            if node["type"] not in definitions:
                return [node["properties"]["h3_modular_key"], slot]
            subgraph = definitions[node["type"]]
            child = Scope(subgraph, self, node)
            return child.resolve_link(subgraph["outputs"][slot]["linkIds"][0])

        def visit(self):
            for node in self.graph["nodes"]:
                if node["type"] in definitions:
                    Scope(definitions[node["type"]], self, node).visit()
                elif "h3_modular_key" in node.get("properties", {}):
                    values = dict(node.get("widgets_values_named", {}))
                    values.pop("control_after_generate", None)
                    for port in node["inputs"]:
                        if port["link"] is not None:
                            values[port["name"]] = self.resolve_link(port["link"])
                    result[node["properties"]["h3_modular_key"]] = {"type": node["type"], "values": values}

    Scope(workflow).visit()
    return result


class Trace:
    """Evaluate control nodes and trace expensive work without running any models."""

    def __init__(self, nodes, overrides=None, media=None):
        self.nodes, self.overrides, self.media = nodes, overrides or {}, media or {}
        self.seen, self.cache = set(), {}

    def value(self, value):
        return self.run(value[0])[value[1]] if isinstance(value, list) else value

    def run(self, key):
        if key in self.cache:
            return self.cache[key]
        self.seen.add(key)
        node = self.nodes[key]
        values, kind = node["values"], node["type"]
        if kind.startswith("Primitive"):
            result = (self.overrides.get(key, values["value"]),)
        elif kind == "YtonEasyMediaLoader":
            result = self.media.get(key, ([], [], []))
        elif kind == "YtonVideoListParser":
            videos = self.value(values["video"])
            result = tuple((videos + [None] * 3)[:3])
        elif kind == "easy isNone":
            value = self.value(values["any"])
            result = (value is None or value == "" or value == 0,)
        elif kind == "easy ifElse":
            branch = "on_true" if self.value(values["boolean"]) else "on_false"
            result = (self.value(values[branch]),)
        elif kind == "ComfyMathExpression":
            args = {name.split(".")[1]: self.value(v) for name, v in values.items() if name.startswith("values.")}
            value = eval(values["expression"], {"__builtins__": {}, "round": round, "max": max}, args)
            result = float(value), int(value), bool(value)
        elif kind == "YtonH3SegmentPlan":
            duration, clip_index, context = (self.value(values[name]) for name in ("duration", "clip_index", "context_frames"))
            visible = max(1, math.floor(duration * 24 + 0.5))
            length = 5 + 17 * max(0, math.ceil((visible + context - 5) / 17))
            result = length, context, length - visible - context, max(0, (clip_index-1)*visible-context), visible
        elif kind == "YtonH3ReplicaPlan":
            video = self.value(values["video"])
            if video is None:
                raise ValueError("复刻模式需要视频")
            visible, context = round(video["duration"] * 24), self.value(values["context_frames"])
            length = 5 + 17 * max(0, math.ceil((visible+context-5)/17))
            result = length, context, length-visible-context
        else:
            # Resolve every input of ordinary nodes; only lazy switches skip branches.
            for value in values.values():
                self.value(value)
            if kind == "GetVideoComponents" and self.value(values["video"]) is None:
                raise AssertionError("空视频进入了解包节点")
            result = (f"{key}:0", f"{key}:1", f"{key}:2", 0, 768, 768, 124)
        self.cache[key] = result
        return result


class ModularWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflows = {}
        cls.graphs = {}
        for variant, suffix in (("3d", "3D-LMS"), ("film", "Film2x")):
            workflow = json.loads((ROOT / f"examples/H3_模块实验_{suffix}.json").read_text(encoding="utf-8"))
            cls.workflows[variant], cls.graphs[variant] = workflow, flatten(workflow)

    def test_every_shipped_wire_matches_the_declared_pipeline(self):
        for variant, graph in self.graphs.items():
            expected = builder.build(variant)
            self.assertEqual(set(graph), {n["key"] for n in expected["nodes"]})
            for node in expected["nodes"]:
                with self.subTest(variant=variant, key=node["key"]):
                    self.assertEqual(graph[node["key"]]["type"], node["type"])
                    for name, value in node["values"].items():
                        if name == "#0":
                            name = "模型加载器"
                        self.assertEqual(graph[node["key"]]["values"][name], list(value) if isinstance(value, tuple) else value)

    def test_empty_uploads_never_execute_video_or_context_processing(self):
        for graph in self.graphs.values():
            for enabled in (False, True):
                trace = Trace(graph, {"enable_context": enabled})
                trace.run("save")
                self.assertFalse({"source_components", "previous_tail", "face_crop", "replica_plan"} & trace.seen)

    def test_connected_previous_video_is_ignored_when_switch_is_off(self):
        for graph in self.graphs.values():
            trace = Trace(graph, {"enable_context": False}, {"previous_media": ([], [{"duration": 5}], [])})
            trace.run("save")
            self.assertNotIn("previous_tail", trace.seen)
            self.assertNotIn("color_match", trace.seen)
            self.assertEqual(trace.run("overlap"), (0.0, 0, False))

    def test_7_5_seconds_adds_and_trims_22_context_frames(self):
        for graph in self.graphs.values():
            trace = Trace(graph, {"duration": 7.5, "enable_context": True}, {"previous_media": ([], [{"duration": 5}], [])})
            trace.run("save")
            length, head, tail = (trace.run(key)[0] for key in ("length", "head", "tail"))
            self.assertEqual((length, head, tail), (209, 22, 7))
            self.assertEqual(length - head - tail, 180)
            self.assertIn("previous_tail", trace.seen)

    def test_single_pass_skips_upscale_and_second_sampler(self):
        for graph in self.graphs.values():
            trace = Trace(graph, {"two_pass": False})
            trace.run("save")
            self.assertFalse({"high_sample", "upscale_film", "upscale_3d", "high_reference"} & trace.seen)
            self.assertEqual(trace.run("low_w")[1], 1344)
            self.assertEqual(trace.run("low_h")[1], 768)

    def test_replica_uses_source_duration_and_never_slices_it(self):
        for graph in self.graphs.values():
            trace = Trace(graph, {"replica_mode": True, "duration": 2.0}, {"media": ([], [{"duration": 7.5}], [])})
            trace.run("save")
            length, head, tail = (trace.run(key)[0] for key in ("length", "head", "tail"))
            self.assertEqual(length-head-tail, 180)
            self.assertNotIn("source_components", trace.seen)
            self.assertNotIn("normal_plan", trace.seen)

    def test_film_noise_schedule_and_audio_lock_are_connected_as_a_unit(self):
        graph = self.graphs["film"]
        self.assertEqual(graph["high_noise"]["type"], "DisableNoise")
        self.assertEqual(graph["high_sample"]["values"]["noise"], ["high_noise", 0])
        self.assertEqual(graph["high_sample"]["values"]["sigmas"], graph["upscale_film"]["values"]["sigmas"])
        self.assertEqual(graph["upscale_film"]["values"]["samples"], ["main_sample", 1])
        self.assertEqual(graph["upscale_film"]["values"]["audio_denoise"], 0)
        self.assertNotIn("positive", graph["upscale_film"]["values"])

    def test_dimensions_are_exactly_two_to_one_after_alignment(self):
        for graph in self.graphs.values():
            for w, h in ((1344,768), (1920,1088), (1280,720)):
                trace = Trace(graph, {"width":w,"height":h})
                self.assertEqual(trace.run("target_width")[1], trace.run("low_w")[1]*2)
                self.assertEqual(trace.run("target_height")[1], trace.run("low_h")[1]*2)

    def test_upscale_preparation_modules_have_identical_interfaces(self):
        modules = [next(s for s in w["definitions"]["subgraphs"] if s["name"].startswith("05")) for w in self.workflows.values()]
        for direction in ("inputs", "outputs"):
            self.assertEqual([(p["name"],p["type"]) for p in modules[0][direction]],
                             [(p["name"],p["type"]) for p in modules[1][direction]])

    def test_parameters_are_editable_on_the_main_canvas(self):
        for workflow in self.workflows.values():
            parameters = next(n for n in workflow["nodes"] if n["title"].startswith("00"))
            self.assertEqual(len(parameters["widgets_values"]), 10)
            self.assertTrue(all(port.get("widget") for port in parameters["inputs"]))

    def test_face_module_has_a_separate_image_input_for_chaining(self):
        for workflow in self.workflows.values():
            face = next(s for s in workflow["definitions"]["subgraphs"] if s["name"].startswith("07"))
            self.assertIn("IMAGE", [p["type"] for p in face["inputs"]])
            self.assertIn("LATENT", [p["type"] for p in face["inputs"]])
            self.assertEqual([p["type"] for p in face["outputs"]], ["IMAGE"])


if __name__ == "__main__":
    unittest.main()
