"""Check the standalone VIDEO context copy and its native loop carry."""

import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


PLUGIN = Path(__file__).resolve().parents[1]
WORKFLOW = PLUGIN / 'examples/H3测试流-传统二采极速-全模态上下文.json'
BASELINE = PLUGIN / 'examples/H3测试流-传统二采极速-调度优化.json'


class OmniContextWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(WORKFLOW.read_text(encoding='utf-8'))
        cls.nodes = {node['id']: node for node in cls.workflow['nodes']}
        cls.links = {link[0]: link for link in cls.workflow['links']}

    def source(self, node_id, name):
        socket = next(item for item in self.nodes[node_id]['inputs'] if item['name'] == name)
        link = self.links[socket['link']]
        return link[1], link[2]

    def test_loop_carries_the_actual_final_video_and_skips_context_on_first_segment(self):
        self.assertEqual(self.source(624, 'video'), (527, 4))
        self.assertEqual(self.source(528, 'next_iteration_value'), (172, 0))
        for switch, original, continued in [(631, 550, 630), (633, 609, 632), (636, 562, 635)]:
            self.assertEqual(self.nodes[switch]['type'], 'ImpactConditionalBranch')
            self.assertEqual(self.source(switch, 'cond'), (527, 1))
            self.assertEqual(self.source(switch, 'tt_value'), (original, 0))
            self.assertEqual(self.source(switch, 'ff_value'), (continued, 0))
        self.assertEqual(self.nodes[527]['widgets_values'][:4], ['For', 0, 2, 1])
        self.assertEqual(self.source(562, 'trim_frames'), (634, 1))
        self.assertEqual(self.nodes[634]['widgets_values'], ['22 * (1 - a)'])

    def test_both_guides_match_omni_context_settings(self):
        self.assertEqual(self.nodes[625]['widgets_values'], [0, 21])
        self.assertEqual(self.nodes[626]['widgets_values'], [21, 1])
        self.assertEqual(self.nodes[627]['widgets_values_named'], {'seed': 0, 'strength': .1})
        self.assertEqual(self.nodes[628]['widgets_values_named'], {'seed': 0, 'strength': 0.0})
        self.assertEqual(self.source(629, 'image_1'), (627, 0))
        self.assertEqual(self.source(629, 'image_2'), (628, 0))
        for guide, reference, feather in [(581, 550, 630), (611, 609, 632)]:
            self.assertEqual(self.nodes[guide]['type'], 'MiniMaxH3AddGuide')
            self.assertEqual(self.source(guide, 'positive'), (reference, 0))
            self.assertEqual(self.source(guide, 'latent'), (reference, 1))
            self.assertEqual(self.source(guide, 'image'), (629, 0))
            self.assertEqual(self.source(guide, 'audio'), (624, 1))
            self.assertEqual(self.nodes[guide]['widgets_values'], [0])
            self.assertEqual(self.source(feather, 'positive'), (guide, 0))
            self.assertEqual(self.nodes[feather]['widgets_values'], [256])

    def test_color_match_is_after_face_refine_and_trim_and_uses_previous_last_frame(self):
        self.assertEqual(self.source(562, 'images'), (618, 0))
        self.assertEqual(self.source(635, 'image_target'), (562, 0))
        self.assertEqual(self.source(635, 'image_ref'), (626, 0))
        self.assertEqual(self.nodes[635]['widgets_values'], ['mkl_lab', 'target_frame', 0, .75])
        self.assertEqual(self.source(172, 'images'), (636, 0))
        self.assertEqual(self.source(172, 'audio'), (562, 1))
        self.assertEqual(self.source(320, 'latent_image'), (550, 1))
        self.assertEqual(self.source(617, 'latent_image'), (608, 0))
        self.assertFalse(any(n['type'] in ('H3-JoinMatch-PGS', 'H3-ContextBlend-PGS', 'H3-LoadLatent-PGS')
                             for n in self.nodes.values()))

    def test_sampling_models_and_source_timeline_are_preserved(self):
        baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
        before = {n['id']: n for n in baseline['nodes']}
        for node_id in (313, 314, 320, 588, 601, 602, 603, 607, 612, 613, 615, 616, 618):
            self.assertEqual(self.nodes[node_id].get('widgets_values'), before[node_id].get('widgets_values'), node_id)
        self.assertEqual(self.workflow['definitions'], baseline['definitions'])
        self.assertEqual(self.source(622, 'signal'), (633, 0))
        self.assertEqual(self.source(622, 'value'), (631, 0))
        self.assertEqual(self.source(623, 'conditioning'), (622, 1))
        self.assertEqual(self.source(320, 'conditioning'), (623, 0))
        self.assertEqual(self.source(614, 'conditioning'), (633, 0))
        for node_id in (605, 561):
            self.assertIn('omni_context/', self.nodes[node_id]['widgets_values'][1])

    def test_graph_has_no_dependency_cycles_and_links_match_both_sockets(self):
        visited, visiting = set(), set()
        def visit(node_id):
            self.assertNotIn(node_id, visiting)
            if node_id in visited:
                return
            visiting.add(node_id)
            for item in self.nodes[node_id].get('inputs', []):
                if item.get('link') is not None:
                    visit(self.links[item['link']][1])
            visiting.remove(node_id)
            visited.add(node_id)
        for node_id in self.nodes:
            visit(node_id)
        for link_id, source, output, target, slot, _ in self.links.values():
            self.assertIn(link_id, self.nodes[source]['outputs'][output]['links'])
            self.assertEqual(self.nodes[target]['inputs'][slot]['link'], link_id)
        for node in self.nodes.values():
            for slot, output in enumerate(node.get('outputs', [])):
                for link_id in output.get('links') or []:
                    self.assertEqual(self.links[link_id][1:3], [node['id'], slot])

    def test_native_loop_skips_absent_video_then_carries_each_previous_result(self):
        from test_h3_video_context import asyncio, execution, torch, InputImpl, Types, Fraction, YtonH3VideoTail
        import nodes
        from comfy_extras import nodes_loop
        from server import PromptServer

        impact_source = PLUGIN.parent / 'ComfyUI-Impact-Pack/modules/impact/logics.py'
        definition = next(n for n in ast.parse(impact_source.read_text(encoding='utf-8')).body
                          if isinstance(n, ast.ClassDef) and n.name == 'ImpactConditionalBranch')
        namespace = {'any_typ': '*'}
        exec(compile(ast.Module(body=[definition], type_ignores=[]), str(impact_source), 'exec'), namespace)
        branch = namespace['ImpactConditionalBranch']
        received, produced, tails = [], [], []

        class EmptyContext:
            @classmethod
            def INPUT_TYPES(cls):
                return {'required': {}}
            RETURN_TYPES = ('IMAGE',)
            FUNCTION = 'run'
            def run(self):
                return (torch.zeros(0, 8, 8, 3),)

        class Tail(YtonH3VideoTail):
            def extract(self, video):
                self_video = produced[-1]
                self.assertion(video is self_video)
                images, audio = super().extract(video)
                tails.append(images.clone())
                return images, audio
            @staticmethod
            def assertion(value):
                if not value:
                    raise AssertionError('Loop did not carry the actual previous VIDEO')

        class Render:
            @classmethod
            def INPUT_TYPES(cls):
                return {'required': {'index': ('INT',), 'context': ('IMAGE',)}}
            RETURN_TYPES = ('VIDEO',)
            FUNCTION = 'run'
            def run(self, index, context):
                received.append((index, len(context)))
                if index:
                    torch.testing.assert_close(context, produced[-1].get_components().images[-22:])
                frames = torch.full((56, 8, 8, 3), (index + 1) / 10)
                audio = {'waveform': torch.zeros(1, 2, 5600), 'sample_rate': 2400}
                video = InputImpl.VideoFromComponents(Types.VideoComponents(images=frames, audio=audio, frame_rate=Fraction(24)))
                produced.append(video)
                return (video,)

        class Output:
            @classmethod
            def INPUT_TYPES(cls):
                return {'required': {'video': ('VIDEO',)}}
            RETURN_TYPES = ()
            FUNCTION = 'run'
            OUTPUT_NODE = True
            def run(self, video):
                return ()

        prompt = {
            '527': {'class_type': 'StartLoop', 'inputs': {'mode': 'For', 'mode.start_iteration_index': 0,
                                                       'mode.max_iteration': 3, 'mode.step': 1, 'cache_iterations': False}},
            'base': {'class_type': 'TestOmniEmptyContext', 'inputs': {}},
            '624': {'class_type': 'TestOmniTail', 'inputs': {'video': ['527', 4]}},
            '631': {'class_type': 'ImpactConditionalBranch', 'inputs': {'cond': ['527', 1], 'tt_value': ['base', 0], 'ff_value': ['624', 0]}},
            '172': {'class_type': 'TestOmniRender', 'inputs': {'index': ['527', 0], 'context': ['631', 0]}},
            '528': {'class_type': 'EndLoop', 'inputs': {'output_value': ['172', 0], 'next_iteration_value': ['172', 0], 'accumulate': False}},
            'out': {'class_type': 'TestOmniOutput', 'inputs': {'video': ['528', 0]}},
        }
        mapping = {**nodes_loop.NODE_CLASS_MAPPINGS, 'ImpactConditionalBranch': branch,
                   'TestOmniEmptyContext': EmptyContext, 'TestOmniTail': Tail, 'TestOmniRender': Render, 'TestOmniOutput': Output}
        server = Mock(client_id=None, last_node_id=None)
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, mapping), patch.object(PromptServer, 'instance', server, create=True):
            valid, errors, outputs, node_errors = asyncio.run(execution.validate_prompt('omni-loop', prompt, None))
            self.assertTrue(valid, (errors, node_errors))
            executor = execution.PromptExecutor(server, cache_type=execution.CacheType.CLASSIC,
                                                cache_args={'ram': 0, 'ram_inactive': 0})
            asyncio.run(executor.execute_async(prompt, 'omni-loop', execute_outputs=outputs))
            self.assertTrue(executor.success, executor.status_messages)
        self.assertEqual(received, [(0, 0), (1, 22), (2, 22)])
        self.assertEqual(len(tails), 2)


if __name__ == '__main__':
    unittest.main()
