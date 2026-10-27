"""Prepare the source at the selected short edge before H3 conditioning."""
import json
import math
from fractions import Fraction
from pathlib import Path
import subprocess
import tempfile


def canvas_dimensions(width, height, resolution):
    if resolution not in ("480", "768"):
        raise ValueError("请选择 480p 或 768p")
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError("视频尺寸无效")
    edge = int(resolution)
    if width >= height:
        return max(32, math.floor(width * edge / height / 32 + .5) * 32), edge
    return edge, max(32, math.floor(height * edge / width / 32 + .5) * 32)


class YuanH3PrepareSource:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video": ("VIDEO",), "resolution": (["480", "768"], {"default": "480"})},
                "optional": {"duration_seconds": ("FLOAT", {"default": 0., "min": 0., "max": 149.66}),
                             "missing_audio": (["silence", "none"], {"default": "silence"})}}

    RETURN_TYPES = ("IMAGE", "AUDIO", "INT", "INT", "INT", "INT", "FLOAT", "STRING", "VIDEO")
    RETURN_NAMES = ("reference_frames", "source_audio", "width", "height", "h3_length", "source_frames", "fps", "summary", "prepared_video")
    FUNCTION = "prepare"
    CATEGORY = "yton-nodes/H3"

    def prepare(self, video, resolution, duration_seconds=0., missing_audio="silence"):
        import torch
        from comfy_api.latest._input_impl.video_types import VideoFromFile, VideoFromComponents
        from comfy_api.latest._util import VideoComponents

        if not math.isfinite(duration_seconds) or not 0 <= duration_seconds <= 3592 / 24:
            raise ValueError("视频时长超出 H3 支持范围")
        limit = min(3592, max(1, math.floor(duration_seconds * 24))) if duration_seconds else 3593
        with tempfile.TemporaryDirectory(prefix="yuan-h3-source-") as directory:
            source = video.get_stream_source()
            start, duration = video.get_active_trim_window()
            if not isinstance(source, str) or start or duration or getattr(video, "_VideoFromFile__crop", None):
                source = str(Path(directory) / "source.mkv")
                video.save_to(source)
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", source],
                                   check=True, capture_output=True, timeout=30)
            stream = json.loads(probe.stdout)["streams"][0]
            sar = stream.get("sample_aspect_ratio", "1:1")
            try:
                sar = float(Fraction(sar.replace(":", "/")))
                if sar <= 0:
                    sar = 1.
            except (ValueError, ZeroDivisionError):
                sar = 1.
            width, height = stream["width"] * sar, stream["height"]
            rotation = next((item["rotation"] for item in stream.get("side_data_list", []) if "rotation" in item), 0)
            if round(rotation) % 180 == 90:
                width, height = height, width
            width, height = canvas_dimensions(width, height, resolution)
            output = str(Path(directory) / "prepared.mkv")
            filters = (f"setpts=PTS-STARTPTS,fps=fps=24:round=near:eof_action=round,"
                       f"scale=w='ceil(max({width},{height}*dar)-1e-6)':"
                       f"h='ceil(max({height},{width}/dar)-1e-6)':flags=lanczos,"
                       f"setsar=1,crop=w={width}:h={height}")
            audio_filter = "asetpts=PTS-STARTPTS" + (f",atrim=end={limit/24:.12f}" if duration_seconds else "")
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", source,
                       "-map", "0:v:0", "-map", "0:a:0?", "-vf", filters, "-af", audio_filter,
                       "-frames:v", str(limit), "-c:v", "ffv1", "-threads", "0", "-c:a", "pcm_s16le", output]
            try:
                subprocess.run(command, check=True, capture_output=True, timeout=180)
            except subprocess.CalledProcessError as error:
                raise ValueError("视频预处理失败：" + error.stderr.decode(errors="replace")[-1200:]) from error
            components = VideoFromFile(output).get_components()
        images, audio = components.images, components.audio
        count, actual_h, actual_w = images.shape[:3]
        if not 1 <= count <= 3592 or (actual_w, actual_h) != (width, height):
            raise ValueError("视频预处理结果尺寸或帧数不正确")
        if audio is None and missing_audio == "silence":
            audio = {"waveform": torch.zeros(1, 2, round(count / 24 * 48000)), "sample_rate": 48000}
        if audio is not None:
            audio = dict(audio, waveform=audio["waveform"][..., :round(count / 24 * audio["sample_rate"])])
        preview = VideoFromComponents(VideoComponents(images=images, audio=audio, frame_rate=Fraction(24)))
        length = 5 + 17 * max(0, math.ceil((count - 5) / 17))
        if length > count:
            images = torch.cat((images, images[-1:].expand(length-count, -1, -1, -1)))
        summary = f"{width} × {height} · 短边 {resolution}px · 24 fps · {count} 帧 · H3 补齐至 {length} 帧"
        return images, audio, width, height, length, count, 24., summary, preview


NODE_CLASS_MAPPINGS = {"YuanH3PrepareSource": YuanH3PrepareSource}
NODE_DISPLAY_NAME_MAPPINGS = {"YuanH3PrepareSource": "H3 源视频 · 短边分辨率"}
