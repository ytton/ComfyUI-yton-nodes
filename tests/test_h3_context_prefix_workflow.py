"""Check the masked prefix reaches both samplers without a scheduling cycle."""

import json
from pathlib import Path
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / "examples/H3测试流-传统二采极速-前缀保护对照.json"


class PrefixWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        cls.nodes = {node["id"]: node for node in cls.workflow["nodes"]}
        cls.links = {link[0]: link for link in cls.workflow["links"]}

    def source(self, node_id, input_name):
        socket = next(item for item in self.nodes[node_id]["inputs"] if item["name"] == input_name)
        link = self.links[socket["link"]]
        return link[1], link[2]

    def test_both_samplers_receive_protected_latents_at_their_own_resolution(self):
        for node_id in (581, 611):
            self.assertEqual(self.nodes[node_id]["widgets_values"][0], "masked_av")
        self.assertEqual(self.source(320, "latent_image"), (581, 2))
        self.assertEqual(self.source(581, "latent"), (550, 1))
        self.assertEqual(self.source(611, "latent"), (608, 0))
        self.assertEqual(self.source(617, "latent_image"), (611, 2))
        self.assertEqual(self.source(614, "conditioning"), (611, 0))
        self.assertEqual(self.source(622, "signal"), (609, 0))

    def test_reference_barrier_and_post_upscale_protection_do_not_form_a_cycle(self):
        visiting, visited = set(), set()
        def visit(node_id):
            self.assertNotIn(node_id, visiting, f"Cycle through node {node_id}")
            if node_id in visited:
                return
            visiting.add(node_id)
            for item in self.nodes[node_id].get("inputs", []):
                if item.get("link") is not None:
                    visit(self.links[item["link"]][1])
            visiting.remove(node_id)
            visited.add(node_id)
        for node_id in self.nodes:
            visit(node_id)

    def test_links_remain_consistent_for_frontend_serialization(self):
        for link_id, source, output, target, slot, _ in self.links.values():
            self.assertIn(link_id, self.nodes[source]["outputs"][output]["links"])
            self.assertEqual(self.nodes[target]["inputs"][slot]["link"], link_id)
        for node in self.nodes.values():
            for slot, output in enumerate(node.get("outputs", [])):
                for link_id in output.get("links") or []:
                    self.assertEqual(self.links[link_id][1:3], [node["id"], slot])

    def test_each_pass_loads_its_own_saved_resolution_in_an_isolated_directory(self):
        low = self.nodes[560]["widgets_values"][1]
        high = self.nodes[610]["widgets_values"][1]
        self.assertNotEqual(low, high)
        self.assertEqual(low, self.nodes[605]["widgets_values"][1])
        self.assertEqual(high, self.nodes[561]["widgets_values"][1])
        self.assertNotIn("scheduled", low + high)


if __name__ == "__main__":
    unittest.main()
