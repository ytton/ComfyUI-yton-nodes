# ComfyUI-yton-nodes

A clean, modular custom node suite for ComfyUI tailored for AI video (especially MiniMax H3 / Hailuo) and image generation workflows.

## Features

1. **分辨率比例控件 (`YtonResolutionSelector`)**
   - Dual-mode switching: **Normal (Standard Image/Video)** vs **MiniMax H3 (Video)**
   - H3 mode strictly enforces 16/32-pixel macroblock alignment (e.g. 1080p -> 1088h, 540p -> 544h).
   - Both modes start at 480p and show nine presets in a three-row grid. H3 mode includes 768p (1.0), 848p (1.2), 944p (1.5), and 1024p (1.8). Provides presets across 8 aspect ratios (16:9, 9:16, 1:1, 4:3, 3:4, 2:3, 3:2, 21:9).
   - The added H3 presets use 768p as the 1.0 baseline: short side = 768 × √multiplier, rounded to a multiple of 16. Width/height adapt to the selected aspect ratio; multiplier labels follow the existing 16:9 convention.
   - Image presets: 480p, 540p, 640p, 720p, 1080p, 2K, 2.5K, 4K, and 6K. The 2.5K tier scales the existing 2K dimensions by approximately 1.25 (16:9: 3200×1800; 1:1: 2560×2560), using even dimensions.
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

## Node panels

- Panels grow with their content and follow node resizing in both canvas and Vue node renderers.
- Traditional node panels keep their width aligned with the node when the selected-node inspector opens.
- Resolution and aspect-ratio selections refresh when reopening a workflow or changing widget values.
- Custom panels are excluded from workflow input serialization.
- After updating frontend files, refresh the ComfyUI page with Ctrl+F5.

### Browser regression

With ComfyUI on `127.0.0.1:8188`, serve the edited assets using
`python -m http.server 8192 --bind 127.0.0.1 --directory web`.
Run `tests/node_panels.browser.js` as a Playwright function with a `page` argument.
It uses an isolated browser context to check layout, zoom, resizing, restored
selections, prompt serialization, and the media loader's initial display.
