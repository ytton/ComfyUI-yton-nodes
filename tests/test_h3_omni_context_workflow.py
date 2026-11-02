"""Check the standalone VIDEO context copy and its native loop carry."""

import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


PLUGIN = Path(__file__).resolve().parents[1]
WORKFLOW = PLUGIN / 'examples/H3测试流-传统二采极速-全模态上下文.json'
BASELINE = PLUGIN / 'examples/H3测试流-传统二采极速-调度优化.json'
PROMPT_FIXTURE = PLUGIN / 'tests/fixtures/h3_omni_context_prompt.json'


def expected_prompt():
    """Keep the original execution recipe, with the explicitly changed reference/size adapters."""
    expected = json.loads(PROMPT_FIXTURE.read_text(encoding='utf-8'))
    for key in ('462', '463', '466'):
        del expected[key]
    expected['639'] = {'class_type': 'YtonH3ReferenceAssets', 'inputs': {
        'images.参考图 1': ['518', 0], 'images.参考图 2': ['495', 0],
        'video_frames': ['588', 0], 'video_audio': ['588', 1]}}
    expected['645'] = {'class_type': 'PrimitiveFloat', 'inputs': {'value': .5}}
    for key in ('550', '609'):
        node = expected[key]
        node['class_type'] = 'YtonH3ReferenceFromAssets'
        node['inputs'] = {k: v for k, v in node['inputs'].items()
                          if not k.startswith(('ref_images.', 'ref_videos.', 'ref_audios.'))}
        node['inputs']['assets'] = ['639', 0]
    expected['618']['inputs'].pop('references.参考图 1')
    expected['618']['inputs']['assets'] = ['639', 0]
    expected['524']['inputs']['assets'] = ['639', 0]
    for key in ('602', '603'):
        expected[key]['inputs'].update(expression='max(32, floor(a * b / 32) * 32)', **{'values.b': ['645', 0]})
    return expected


class WorkflowView:
    """Resolve native subgraphs and promoted widgets by stable original node identity."""

    def __init__(self, workflow):
        self.definitions = {s['id']: s for s in workflow['definitions']['subgraphs']}
        self.nodes, self.scopes = {}, {}
        self.root = self.Scope(self, workflow)
        self.root.visit()

    @staticmethod
    def key(node):
        key = str(node.get('properties', {}).get('h3_layout_key', node['id']))
        return int(key) if key.isdecimal() else key

    def source(self, node_id, name):
        node = self.nodes[node_id]
        socket = next(i for i in node['inputs'] if i['name'] == name)
        key, slot = self.scopes[node_id].resolve_link(socket['link'])
        return key, slot

    def prompt(self, expected):
        result = {}
        for key, expected_node in expected.items():
            node_key = int(key) if key.isdecimal() else key
            node, scope = self.nodes[node_key], self.scopes[node_key]
            values = dict(node.get('widgets_values_named', {}))
            names = set(expected_node['inputs'])
            for port in node.get('inputs', []):
                if port.get('link') is not None:
                    values[port['name']] = scope.resolve_link(port['link'])
                    names.add(port['name'])
            result[key] = {'class_type': node['type'], 'inputs': {name: values[name] for name in names}}
        return result

    class Scope:
        def __init__(self, view, graph, parent=None, host=None):
            self.view, self.graph, self.parent, self.host = view, graph, parent, host
            self.nodes = {str(n['id']): n for n in graph['nodes']}
            self.links = {str(l[0] if isinstance(l, list) else l['id']): l for l in graph['links']}

        def resolve_link(self, link_id):
            link = self.links[str(link_id)]
            source, slot = (link[1:3] if isinstance(link, list) else (link['origin_id'], link['origin_slot']))
            if str(source) == '-10':
                port = self.host['inputs'][slot]
                if port.get('link') is not None:
                    return self.parent.resolve_link(port['link'])
                names = [p['widget']['name'] for p in self.host['inputs'] if p.get('widget')]
                return self.host['widgets_values'][names.index(port['widget']['name'])]
            node = self.nodes[str(source)]
            if node['type'] in self.view.definitions:
                graph = self.view.definitions[node['type']]
                return self.__class__(self.view, graph, self, node).resolve_link(graph['outputs'][slot]['linkIds'][0])
            return [self.view.key(node), slot]

        def visit(self):
            for node in self.nodes.values():
                key = self.view.key(node)
                self.view.nodes[key], self.view.scopes[key] = node, self
                if node['type'] in self.view.definitions:
                    self.__class__(self.view, self.view.definitions[node['type']], self, node).visit()


class OmniContextWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(WORKFLOW.read_text(encoding='utf-8'))
        cls.view = WorkflowView(cls.workflow)
        cls.nodes = cls.view.nodes

    def source(self, node_id, name):
        return self.view.source(node_id, name)

    def test_loop_carries_the_actual_final_video_and_skips_context_on_first_segment(self):
        self.assertEqual(self.source(624, 'video'), (527, 4))
        self.assertEqual(self.source(528, 'next_iteration_value'), (172, 0))
        self.assertEqual(self.source(528, 'output_value'), (202, 0))
        self.assertFalse(any(item.get('link') is not None for item in self.nodes[528]['inputs']
                             if item['name'].startswith('terminations.')))
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
        for node_id, strength in ((627, .1), (628, 0.0)):
            self.assertEqual(self.nodes[node_id]['widgets_values_named']['seed'], 0)
            self.assertEqual(self.nodes[node_id]['widgets_values_named']['strength'], strength)
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
        self.assertFalse(any(n['type'] in ('H3-JoinMatch-PGS', 'H3-ContextBlend-PGS', 'H3-LoadLatent-PGS', 'H3-SaveLatent-PGS')
                             for n in self.nodes.values()))

    def test_sampling_models_and_source_timeline_are_preserved(self):
        baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
        before = {n['id']: n for n in baseline['nodes']}
        for node_id in (313, 314, 320, 588, 601, 607, 612, 613, 615, 616, 618):
            self.assertEqual(self.nodes[node_id].get('widgets_values'), before[node_id].get('widgets_values'), node_id)
        original = {s['id'] for s in baseline['definitions']['subgraphs']}
        self.assertTrue(original.issubset(self.view.definitions))
        self.assertEqual(self.source(622, 'signal'), (633, 0))
        self.assertEqual(self.source(622, 'value'), (631, 0))
        self.assertEqual(self.source(623, 'conditioning'), (622, 1))
        self.assertEqual(self.source(320, 'conditioning'), (623, 0))
        self.assertEqual(self.source(614, 'conditioning'), (633, 0))
        self.assertTrue({421, 561, 605}.isdisjoint(self.nodes))

    def test_graph_has_no_dependency_cycles_and_links_match_both_sockets(self):
        expected = expected_prompt()
        prompt = self.view.prompt(expected)
        visited, visiting = set(), set()
        def visit(node_id):
            self.assertNotIn(node_id, visiting)
            if node_id in visited:
                return
            visiting.add(node_id)
            for value in prompt[str(node_id)]['inputs'].values():
                if isinstance(value, list) and len(value) == 2 and str(value[0]) in prompt:
                    visit(str(value[0]))
            visiting.remove(node_id)
            visited.add(node_id)
        for node_id in prompt:
            visit(node_id)
        for graph in [self.workflow, *self.view.definitions.values()]:
            nodes = {str(n['id']): n for n in graph['nodes']}
            links = {}
            for item in graph['links']:
                if isinstance(item, list):
                    link_id, source, output, target, slot, _ = item
                else:
                    link_id, source, output, target, slot = (item[name] for name in
                        ('id', 'origin_id', 'origin_slot', 'target_id', 'target_slot'))
                links[link_id] = (str(source), output, str(target), slot)
                source_links = (graph['inputs'][output]['linkIds'] if str(source) == '-10'
                                else nodes[str(source)]['outputs'][output]['links'])
                self.assertIn(link_id, source_links)
                if str(target) == '-20':
                    self.assertIn(link_id, graph['outputs'][slot]['linkIds'])
                else:
                    self.assertEqual(nodes[str(target)]['inputs'][slot]['link'], link_id)
            for node in nodes.values():
                for slot, output in enumerate(node.get('outputs', [])):
                    for link_id in output.get('links') or []:
                        self.assertEqual(links[link_id][:2], (str(node['id']), slot))

    def test_packaging_preserves_every_executable_input_and_exposes_controls(self):
        expected = expected_prompt()
        # Fixture was exported from the original graph by native graphToPrompt.
        actual = self.view.prompt(expected)
        # JSON uses string node identifiers; graph source resolution preserves original ints.
        for node in actual.values():
            for name, value in node['inputs'].items():
                if isinstance(value, list) and len(value) == 2 and str(value[0]) in expected:
                    node['inputs'][name] = [str(value[0]), value[1]]
        self.assertEqual(actual, expected)
        modules = {n['properties'].get('h3_layout_module'): n for n in self.workflow['nodes']}
        for module, names in {'second': {'model_name', 'noise_seed', 'sampler_name', 'sigmas', 'chunks'},
                              'face': {'enabled', 'face_count', 'sigmas', 'reverse'}}.items():
            host = modules[module]
            widgets = {p['name'] for p in host['inputs'] if p.get('widget')}
            self.assertTrue(names.issubset(widgets))
            self.assertIn(host['type'], self.view.definitions)
        self.assertEqual(len(self.workflow['nodes']), 20)
        for module, labels in {'conditions': {'width': '首采宽度', 'height': '首采高度',
                                              'image': '上段 22 帧', 'audio': '上段音频'},
                                'face': {'enabled': '开启修脸'},
                                'output': {'image_ref': '上段末帧', 'values.a': '是否首段'}}.items():
            host = modules[module]
            for name, label in labels.items():
                self.assertEqual(next(p['label'] for p in host['inputs'] if p['name'] == name), label)

    def test_reference_collection_and_first_pass_scale_reach_every_consumer(self):
        for node_id in (550, 609, 618, 524):
            self.assertEqual(self.source(node_id, 'assets'), (639, 0))
        for node_id in (602, 603):
            self.assertEqual(self.source(node_id, 'values.b'), (645, 0))
        self.assertEqual(self.source(550, 'width'), (602, 1))
        self.assertEqual(self.source(550, 'height'), (603, 1))
        self.assertEqual(self.source(609, 'width'), (601, 0))
        self.assertEqual(self.source(609, 'height'), (601, 1))
        self.assertEqual(self.source(607, 'mode.width'), (601, 0))
        self.assertEqual(self.source(607, 'mode.height'), (601, 1))
        from math import floor
        for scale in (.33, .5, .6, .75, 1):
            for node_id, dimension in ((602, 1920), (603, 1088)):
                expression = self.nodes[node_id]['widgets_values'][0]
                size = eval(expression, {'__builtins__': {}, 'max': max, 'floor': floor}, {'a': dimension, 'b': scale})
                self.assertEqual(size % 32, 0)
                self.assertLessEqual(abs(size-dimension*scale), 32)

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
