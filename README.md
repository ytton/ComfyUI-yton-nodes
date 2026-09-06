# ComfyUI-yton-nodes

A clean, modular custom node suite for ComfyUI tailored for AI video (especially MiniMax H3 / Hailuo) and image generation workflows.

## Features

1. **yton Resolution Selector (`YtonResolutionSelector`)**
   - Dual-mode switching: **Normal (Standard Image/Video)** vs **MiniMax H3 (Video)**
   - H3 mode strictly enforces 16/32-pixel macroblock alignment (e.g. 1080p -> 1088h, 540p -> 544h).
   - Supports 360p, 480p, 540p, 640p, 720p, 1080p, 1K, 2K, 4K across 8 aspect ratios (16:9, 9:16, 1:1, 4:3, 3:4, 2:3, 3:2, 21:9).
   - Outputs: `width`, `height`, `aspect_ratio`, `max_side`, `min_side`, `h3_mp` (compute multiplier), `resolution_str`.

2. **yton Easy Media Loader (`YtonEasyMediaLoader`)**
   - Clean UI inspired by canvas tools with quota counters for Images, Audios, and Videos (default H3 quotas: 9 images, 3 audios, 3 videos).
   - Card previews for images, video thumbnails with duration badge, and audio rows.
   - Outputs unified `media_bundle` dict plus discrete slots: `image_1`~`image_9`, `audio_1`~`audio_3`, `video_1`~`video_3`.
   - Fail-safe quota validation in Python backend.

## Installation

### Method 1: Git Clone into ComfyUI custom_nodes
```bash
cd custom_nodes
git clone https://github.com/your-username/ComfyUI-yton-nodes.git
```

### Method 2: RunningHub
Submit the git repository URL into RunningHub custom node management or clone inside your personal container.
