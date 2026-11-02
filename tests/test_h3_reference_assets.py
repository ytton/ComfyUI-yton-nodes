"""Exercise optional, ordered references through both H3 passes and face expansion on CPU."""

import importlib.util
from unittest.mock import Mock, patch
import unittest

from test_h3_video_context import torch, execution, asyncio, PLUGIN
import nodes
from comfy_api.latest import io
from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo
from video_context_test.reference_runtime import YtonH3ReferenceAssets, YtonH3ReferenceFromAssets
from video_context_test.face_runtime import YtonH3FaceRefine


class ReferenceAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = PLUGIN.parent / 'ComfyUI-MiniMaxH3-Ref-PGS/nodes.py'
        spec = importlib.util.spec_from_file_location('h3_pgs_asset_test', path)
        pgs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pgs)
        cls.mapping = pgs.NODE_CLASS_MAPPINGS
        for node in (YtonH3ReferenceAssets, YtonH3ReferenceFromAssets, YtonH3FaceRefine):
            node.GET_SCHEMA()

    def collection(self, count, video=False):
        pictures = [torch.full((1, 32, 32, 3), (i+1)/20) for i in range(count)]
        frames = torch.zeros(22, 32, 32, 3) if video else None
        audio = {'waveform': torch.zeros(1, 2, 3200), 'sample_rate': 32000} if video else None
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, self.mapping):
            result = YtonH3ReferenceAssets.execute(
                images={f'参考图 {i+1}': image for i, image in enumerate(pictures)},
                video_frames=frames, video_audio=audio)
        return result.result[0], result.result[1], pictures

    def test_zero_one_three_and_twelve_references_remain_independent_and_keep_pgs_labels(self):
        for count in (0, 1, 3, 12):
            with self.subTest(count=count):
                assets, schedule, pictures = self.collection(count, video=True)
                labels = [a['nativeLabel'] for a in schedule['assets']]
                self.assertEqual(labels, [f'<Picture {i+1}>' for i in range(count)] + ['<Video 1>', '<Audio 1>'])
                self.assertEqual(len(assets['images']), count)
                for actual, expected in zip(assets['images'], pictures):
                    self.assertIs(actual, expected)
                for width, height in ((960, 544), (1920, 1088)):
                    with patch.object(MiniMaxH3ReferenceToVideo, 'execute', return_value=io.NodeOutput(None, None)) as encode:
                        YtonH3ReferenceFromAssets.execute(
                            clip=object(), prompt='原提示词', width=width, height=height, length=175, assets=assets)
                    values = encode.call_args.kwargs
                    self.assertEqual(len(values['ref_images']), count)
                    for i, image in enumerate(pictures):
                        self.assertIs(values['ref_images'][f'ref_image_{i}'], image)
                    self.assertIs(values['ref_videos']['ref_video_0'], assets['video_frames'])
                    self.assertIs(values['ref_audios']['ref_audio_0'], assets['video_audio'])

    def test_absent_scene_and_empty_collection_do_not_create_dummy_references(self):
        for count in (0, 1, 3):
            assets, schedule, pictures = self.collection(count)
            self.assertEqual(len(schedule['assets']), count)
            with patch.object(MiniMaxH3ReferenceToVideo, 'execute', return_value=io.NodeOutput(None, None)) as encode:
                YtonH3ReferenceFromAssets.execute(clip=object(), prompt='', width=32, height=32, length=22, assets=assets)
            self.assertEqual(encode.call_args.kwargs['ref_videos'], {})
            self.assertEqual(encode.call_args.kwargs['ref_audios'], {})
        inputs = YtonH3ReferenceAssets.INPUT_TYPES()
        self.assertEqual(inputs['required'], {})
        self.assertEqual(inputs['optional']['images'][1]['template']['min'], 0)
        self.assertGreater(len(inputs['optional']['images'][1]['template']['names']), 9)

    def test_separate_outputs_match_native_pgs_schedule_without_generation_tensors(self):
        references, schedule, _ = self.collection(3, video=True)
        self.assertEqual(set(references), {'images', 'video_frames', 'video_audio'})
        self.assertEqual(set(schedule), {'assets'})
        info = YtonH3ReferenceAssets.GET_NODE_INFO_V1()
        self.assertEqual(info['output'], ['H3_REFERENCE_ASSETS', 'H3_PGS_ASSETS'])
        self.assertEqual(info['output_name'], ['参考素材', 'PGS schedule'])
        editor = self.mapping['MiniMaxH3RefPGSScenePromptEditor']()
        result = asyncio.run(editor.passthrough(
            prompt='@Picture_1 与 @Picture_3 参考 @Video_1 和 @Video_1_audio', assets=schedule))
        self.assertEqual(result['result'][0]['shots'][0]['prompt'],
                         '<Picture 1> 与 <Picture 3> 参考 <Video 1> 和 <Audio 1>')

    def test_pgs_markers_supply_real_images_and_aliases_to_every_consumer(self):
        images = [torch.full((1, 32, 32, 3), i/10) for i in range(1, 5)]
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, self.mapping):
            register = self.mapping['MiniMaxH3RefPGSPictureAsset']()
            marked, _ = register.register(images[0], 'Hero', '人物')
            marked, _ = register.register(images[1], 'Scene', '场景', previous=marked)
            collection, schedule = YtonH3ReferenceAssets.execute(pgs_images=marked,
                images={'参考图 4': images[3], '参考图 3': images[2]}).result
        self.assertEqual([a['alias'] for a in schedule['assets']], ['Hero', 'Scene', 'Picture_3', 'Picture_4'])
        self.assertEqual([a['nativeLabel'] for a in schedule['assets']], [f'<Picture {i}>' for i in range(1, 5)])
        for actual, expected in zip(collection['images'], images):
            self.assertIs(actual, expected)
        # Exercise the same resolver used by the PGS prompt editor at execution time.
        resolver = register.register.__globals__['_resolve_aliases_to_native']
        self.assertEqual(resolver('@Hero 与 @Scene、@Picture_3、@Picture_4', schedule['assets']),
                         '<Picture 1> 与 <Picture 2>、<Picture 3>、<Picture 4>')
        for width in (960, 1920):
            with patch.object(MiniMaxH3ReferenceToVideo, 'execute', return_value=io.NodeOutput(None, None)) as encode:
                YtonH3ReferenceFromAssets.execute(clip=object(), prompt='', width=width, height=32,
                                                 length=22, assets=collection)
            for actual, expected in zip(encode.call_args.kwargs['ref_images'].values(), images):
                self.assertIs(actual, expected)
        result = YtonH3FaceRefine.execute(images=['frames', 0], model=['model', 0], clip=['clip', 0],
                                         vae=['vae', 0], assets=collection, face_count=2)
        refs = [n['inputs'] for n in result.expand.values() if n['class_type'] == 'MiniMaxH3ReferenceToVideo']
        self.assertEqual(len(refs), 2)
        for values in refs:
            for i, image in enumerate(images):
                self.assertIs(values[f'ref_images.ref_image_{i}'], image)

    def test_pgs_metadata_without_image_tensors_reports_restart_instead_of_silently_losing_references(self):
        with self.assertRaisesRegex(ValueError, '重启 ComfyUI'):
            YtonH3ReferenceAssets.execute(pgs_images={'assets': [{'kind': 'picture', 'alias': 'Hero'}]})

    def test_native_pgs_video_and_audio_nodes_preserve_registered_images(self):
        image = torch.zeros(1, 32, 32, 3)
        marked, _ = self.mapping['MiniMaxH3RefPGSPictureAsset']().register(image, 'Hero', '人物')
        marked, _ = self.mapping['MiniMaxH3RefPGSVideoAsset']().register(image, 'Video', '视频', previous=marked)
        marked, _ = self.mapping['MiniMaxH3RefPGSAudioAsset']().register({}, 'Voice', '声音', previous=marked)
        collection, schedule = YtonH3ReferenceAssets.execute(pgs_images=marked).result
        self.assertEqual([a['alias'] for a in schedule['assets']], ['Hero'])
        self.assertIs(collection['images'][0], image)

    def test_every_face_uses_the_same_picture_numbering_as_both_sampling_passes(self):
        assets, schedule, pictures = self.collection(4)
        result = YtonH3FaceRefine.execute(images=['frames', 0], model=['model', 0], clip=['clip', 0],
                                         vae=['vae', 0], assets=assets, face_count=3)
        graph = {key.split('.')[-1]: value for key, value in result.expand.items()}
        for face in range(3):
            values = graph[f'face_{face}_reference']['inputs']
            for i, picture in enumerate(pictures):
                self.assertIs(values[f'ref_images.ref_image_{i}'], picture)
            self.assertEqual(graph[f'face_{face}_crop']['inputs']['select_index'], face)

    def test_native_reference_encoder_receives_all_images_in_order(self):
        class Clip:
            def tokenize(self, prompt, minimax_ref_items):
                self.items = minimax_ref_items
                return prompt
            def encode_from_tokens_scheduled(self, tokens):
                return [[torch.zeros(1, 2, 4), {}]]

        class Vae:
            def encode(self, frames):
                return torch.full((1, 24, 2, frames.shape[1]//16, frames.shape[2]//16), float(frames.mean()))

        for count in (0, 3, 12):
            assets, schedule, pictures = self.collection(count)
            clip = Clip()
            result = YtonH3ReferenceFromAssets.execute(
                clip=clip, vae=Vae(), prompt='每张参考图各自定义其用途', width=32, height=32, length=22, assets=assets)
            self.assertEqual(len(clip.items), count)
            for actual, image in zip(clip.items, pictures):
                self.assertEqual(actual['type'], 'image')
                # Native lanczos goes through the 8-bit image resize path.
                torch.testing.assert_close(actual['data'], image, atol=1/255, rtol=0)
            self.assertEqual(len(result.result[0][0][1].get('minimax_refs', [])), count)

    def test_native_executor_requests_assets_only_when_face_refinement_is_enabled(self):
        assets, _, _ = self.collection(3)
        called, expanded = [], []

        class Source:
            @classmethod
            def INPUT_TYPES(cls):
                return {'required': {}}
            RETURN_TYPES = ('H3_REFERENCE_ASSETS',)
            FUNCTION = 'run'
            def run(self):
                called.append(True)
                return (assets,)

        class Probe(YtonH3FaceRefine):
            @classmethod
            def execute(cls, **inputs):
                result = super().execute(**inputs)
                expanded.append(result.expand)
                return io.NodeOutput(inputs['images'], expand={})

        class Output:
            @classmethod
            def INPUT_TYPES(cls):
                return {'required': {'image': ('IMAGE',)}}
            RETURN_TYPES = ()
            FUNCTION = 'run'
            OUTPUT_NODE = True
            def run(self, image):
                return ()

        prompt = {'source': {'class_type': 'TestReferenceSource', 'inputs': {}},
                  'face': {'class_type': 'TestReferenceFace', 'inputs': {
                      'images': torch.zeros(5, 32, 32, 3), 'model': ['unused', 0], 'clip': ['unused', 1],
                      'vae': ['unused', 2], 'assets': ['source', 0], 'enabled': False, 'sigmas': '',
                      'prompt': '', 'face_count': 1, 'reverse': False}},
                  'out': {'class_type': 'TestReferenceOutput', 'inputs': {'image': ['face', 0]}}}
        mapping = {'TestReferenceSource': Source, 'TestReferenceFace': Probe, 'TestReferenceOutput': Output}
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, mapping):
            for enabled in (False, True):
                prompt['face']['inputs']['enabled'] = enabled
                executor = execution.PromptExecutor(Mock(client_id=None, last_node_id=None),
                    cache_type=execution.CacheType.NONE, cache_args={'ram': 0, 'ram_inactive': 0})
                asyncio.run(executor.execute_async(prompt, f'references-{enabled}', execute_outputs=['out']))
                self.assertTrue(executor.success, executor.status_messages)
        self.assertEqual(called, [True])
        self.assertEqual(expanded[0], {})
        self.assertTrue(any(n['class_type'] == 'MiniMaxH3ReferenceToVideo' for n in expanded[1].values()))


if __name__ == '__main__':
    unittest.main()
