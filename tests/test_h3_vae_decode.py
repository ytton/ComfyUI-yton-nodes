"""H3 decode switching preserves sampling and uses the installed fast decoder."""

import importlib.util
import sys
import types
import unittest
from unittest.mock import Mock, patch

from test_h3_video_context import PLUGIN, torch, execution, asyncio
from test_h3_omni_variants import VARIANTS, expanded
from video_context_test.omni_decode import DECODE_MODES, REFERENCE_DETAIL_MODE


def sampling_graph(graph):
    def normalize(value):
        if isinstance(value, list):
            if len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                return [value[0].split(".")[-1], value[1]]
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value
    return normalize({key: value for key, value in graph.items() if key not in ("frames", "decode_vae")})


class VaeDecodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = types.ModuleType("h3_fast_decode_contract")
        package.__path__ = [str(PLUGIN.parent / "ComfyUI-MiniMaxH3_LatentUpscaler")]
        sys.modules[package.__name__] = package
        spec = importlib.util.spec_from_file_location(package.__name__ + ".vae_decode",
                                                      package.__path__[0] + "/vae_decode.py")
        cls.native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.native)
        spec = importlib.util.spec_from_file_location("h3_detail_contract", PLUGIN.parent / "ComfyUI-H3-X2-Detailed" / "nodes.py")
        cls.detail = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.detail)

    def test_all_three_nodes_expose_decode_modes_with_standard_default(self):
        for cls in VARIANTS.values():
            required = cls.INPUT_TYPES()["required"]
            self.assertEqual(required["vae_decode_mode"][0], ["标准解码", "X2 VAE 解码", REFERENCE_DETAIL_MODE])
            self.assertEqual(required["vae_decode_mode"][1]["default"], "标准解码")
            self.assertIn(required["x2_vae_name"][1]["default"], required["x2_vae_name"][0])

    def test_switching_decoder_preserves_every_sampling_context_and_face_node(self):
        for cls in VARIANTS.values():
            for sampling_mode in ("单采", "二采"):
                settings = dict(sampling_mode=sampling_mode, width=1920, height=1088,
                                enable_context=True, previous_video=["previous", 0], image=["ref", 0],
                                face_refine=True, face_count=2, duration=7.5)
                standard = expanded(cls, **settings)
                with self.subTest(plan=cls.SAMPLING_PLAN, sampling=sampling_mode):
                    actual = expanded(cls, **settings, vae_decode_mode="X2 VAE 解码")
                    self.assertEqual(sampling_graph(standard), sampling_graph(actual))

    def test_detail_mode_enhances_once_and_reuses_images_without_changing_sampling(self):
        for cls in VARIANTS.values():
            for sampling_mode in ("单采", "二采"):
                with self.subTest(plan=cls.SAMPLING_PLAN, sampling=sampling_mode):
                    settings = dict(sampling_mode=sampling_mode, image=["ref", 0], face_refine=True,
                                    face_count=2, enable_context=True, previous_video=["previous", 0])
                    standard = expanded(cls, **settings)
                    actual = expanded(cls, **settings, vae_decode_mode=REFERENCE_DETAIL_MODE,
                                      x2_vae_name="detail.safetensors", reference_detail_strength=0.75)
                    detail = actual.pop("reference_detail")
                    self.assertEqual(detail["class_type"], "MiniMaxH3X2DetailedUpscale")
                    self.assertEqual(detail["inputs"], dict(images=["ref", 0], detail_vae="detail.safetensors", detail_strength=0.75))
                    self.assertEqual(set(detail["inputs"]), set(self.detail.MiniMaxH3X2DetailedUpscale.INPUT_TYPES()["required"]))
                    self.assertEqual(actual["decode_vae"]["inputs"]["vae_name"], "detail.safetensors")
                    self.assertEqual(actual["frames"]["class_type"], "MiniMaxH3VAEDecodeFast")
                    refs = [node for node in actual.values() if node["class_type"] == "YtonMiniMaxH3ReferenceToVideo"]
                    self.assertGreaterEqual(len(refs), 2)
                    for node in refs:
                        link = node["inputs"]["image"]
                        self.assertTrue(link[0].endswith("reference_detail"))
                        self.assertEqual(link[1], 0)
                        node["inputs"]["image"] = ["ref", 0]
                    self.assertEqual(sampling_graph(standard), sampling_graph(actual))

    def test_no_images_skips_detail_and_keeps_optional_media_path(self):
        for cls in VARIANTS.values():
            for mode in DECODE_MODES:
                graph = expanded(cls, vae_decode_mode=mode)
                self.assertNotIn("reference_detail", graph)
                self.assertNotIn("image", graph["reference"]["inputs"])

    def test_comfy_maps_different_sized_reference_images_in_order(self):
        node = self.detail.MiniMaxH3X2DetailedUpscale()
        refs = [torch.full((1, 32, 64, 3), 0.25), torch.full((1, 64, 32, 3), 0.75)]
        node.upscale = Mock(side_effect=lambda images, detail_vae, detail_strength: (images, images))
        outputs = asyncio.run(execution._async_map_node_over_list("test", "detail", node,
            dict(images=refs, detail_vae=["detail.safetensors"], detail_strength=[1.0]), node.FUNCTION))
        self.assertEqual(node.upscale.call_count, 2)
        for index, call in enumerate(node.upscale.call_args_list):
            self.assertIs(call.kwargs["images"], refs[index])
            self.assertEqual(call.kwargs["detail_strength"], 1.0)
        merged = execution.merge_result_data(outputs, node)
        for index in range(2):
            self.assertIs(merged[0][index], refs[index])

    def test_standard_mode_uses_loader_vae_without_loading_x2_weights(self):
        for cls in VARIANTS.values():
            graph = expanded(cls, vae_decode_mode="标准解码", x2_vae_name="unused.safetensors")
            self.assertNotIn("decode_vae", graph)
            self.assertEqual(graph["frames"]["class_type"], "VAEDecode")
            self.assertTrue(graph["frames"]["inputs"]["vae"][0].endswith("models"))
            self.assertEqual(graph["frames"]["inputs"]["vae"][1], 2)

    def test_x2_only_replaces_final_video_vae_and_keeps_author_settings(self):
        for cls in VARIANTS.values():
            graph = expanded(cls, vae_decode_mode="X2 VAE 解码", x2_vae_name="test-x2.safetensors")
            decode = graph["frames"]["inputs"]
            self.assertEqual(graph["decode_vae"]["class_type"], "VAELoader")
            self.assertEqual(graph["decode_vae"]["inputs"]["vae_name"], "test-x2.safetensors")
            self.assertTrue(decode["vae"][0].endswith("decode_vae"))
            self.assertTrue(decode["tiling"])
            self.assertEqual((decode["tile_size"], decode["tile_overlap"]), (256, 64))
            self.assertEqual(decode["output_device"], "cpu")
            self.assertFalse(decode["temporal_tiling"])
            self.assertEqual(graph["sound"]["class_type"], "VAEDecodeAudio")
            self.assertEqual(graph["sound"]["inputs"]["vae"][1], 3)

    def test_tile_controls_match_installed_decoder_interface(self):
        schema = self.native.MiniMaxH3VAEDecodeFast.INPUT_TYPES()
        for cls in VARIANTS.values():
            graph = expanded(cls, vae_decode_mode="X2 VAE 解码", vae_tile_size=512, vae_tile_overlap=128)
            inputs = graph["frames"]["inputs"]
            self.assertEqual(set(inputs), set(schema["required"]))
            self.assertEqual((inputs["tile_size"], inputs["tile_overlap"]), (512, 128))

    def test_installed_decoder_pixel_shuffles_x2_rgb_and_restores_vae_on_cpu(self):
        class Inner:
            tiling, tile_size, tile_overlap_min = False, 512, 128
            decoder = types.SimpleNamespace(out_channels=3, patch_size_t=1, patch_size=4,
                                             proj_out=types.SimpleNamespace(weight=torch.empty(192, 1)))
            pixel_mean = torch.zeros(1, 3, 1, 1, 1)
            pixel_std = torch.ones(1, 3, 1, 1, 1)

            def decode_output_shape(self, shape):
                return (1, self.decoder.out_channels, 5, 32, 32)

            def decode(self, samples, output_buffer):
                self.decoded_channels = self.decoder.out_channels
                self.decoded_settings = (self.tiling, self.tile_size, self.tile_overlap_min)
                self.normalization_shape = tuple(self.pixel_mean.shape)
                output_buffer.copy_(torch.arange(12).reshape(1, 12, 1, 1, 1))

        inner = Inner()
        mean, std = inner.pixel_mean, inner.pixel_std
        vae = types.SimpleNamespace(first_stage_model=inner, device=torch.device("cpu"),
            vae_dtype=torch.float32, disable_offload=False, patcher=object(),
            throw_exception_if_invalid=Mock(), memory_used_decode=lambda *args: 0,
            vae_output_dtype=lambda: torch.float32, process_output=lambda images: images)
        with patch.object(self.native.model_management, "load_models_gpu"), \
             patch.object(self.native, "_debug_vae_load_state"), patch("builtins.print"):
            images, = self.native.MiniMaxH3VAEDecodeFast().decode(
                {"samples": torch.zeros(1, 24, 2, 2, 2)}, vae)
        self.assertEqual(tuple(images.shape), (5, 64, 64, 3))
        self.assertEqual(images[0, 0, 0].tolist(), [0, 4, 8])
        self.assertEqual(images[0, 1, 1].tolist(), [3, 7, 11])
        self.assertEqual(inner.decoded_channels, 12)
        self.assertEqual(inner.decoded_settings, (True, 256, 64))
        self.assertEqual(inner.normalization_shape, (1, 12, 1, 1, 1))
        self.assertEqual((inner.tiling, inner.tile_size, inner.tile_overlap_min), (False, 512, 128))
        self.assertEqual(inner.decoder.out_channels, 3)
        self.assertIs(inner.pixel_mean, mean)
        self.assertIs(inner.pixel_std, std)


if __name__ == "__main__":
    unittest.main()
