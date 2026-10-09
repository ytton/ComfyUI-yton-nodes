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

2. **媒体加载器 (`YtonEasyMediaLoader`)**
   - 固定三列卡片：9 张图片、3 个视频、3 个音频，分类支持折叠。
   - 新建节点默认宽度 640，图片展开，视频和音频折叠；保存后保留用户选择的尺寸与折叠状态。
   - 没有输入连线端口。点击槽位选择文件，或直接拖入文件；支持多文件上传、预览、播放、删除及同类槽位交换。
   - 选中节点后按 Ctrl+V，可粘贴剪贴板中的图片、视频或音频文件，自动分类并填入第一个空槽位，不覆盖已有素材；视频和音频粘贴后自动展开。支持同时粘贴多个文件，槽位满时提示先移除素材；在文本输入框中粘贴仍保留原有行为。
   - 三个原生列表输出：`image`（IMAGE）、`video`（VIDEO）、`audio`（AUDIO），端口显示 ComfyUI 列表图标。
   - 文件名保存在 `image_1`～`image_9`、`video_1`～`video_3`、`audio_1`～`audio_3` 的 widget 值中，外部 API 可直接填写。
   - 面板的槽位编号固定；输出列表仅包含已加载的素材，按槽位顺序排列。图片为张量、视频为原生 VIDEO 对象、音频为 waveform/sample_rate 字典，可以直接连接 EasyMedia 的列表处理节点。

3. **素材解析节点**
   - 三个列表解析节点的输入分别为 `image`、`video`、`audio`，使用 ComfyUI 原生列表图标；输出为各个单项素材。
   - 图片列表解析：IMAGE 列表 → `image_1`～`image_9`。
   - 视频列表解析：VIDEO 列表 → `video_1`～`video_3`。
   - 音频列表解析：AUDIO 列表 → `audio_1`～`audio_3`。
   - 图片解析：标准 `IMAGE` → RGB 图片、`MASK`；RGBA 输入会解析透明区域，RGB 输入的遮罩全为零。
   - 视频解析：单个 `VIDEO` → 图像帧批次（IMAGE）、帧计数（INT）、原音轨（AUDIO）、视频信息（VHS_VIDEOINFO）。视频信息包含源视频与解析结果的帧率、帧数、时长和宽高，可连接 Video Helper Suite 的视频信息节点；没有音轨时音频为空。
   - 音频解析：单个音频素材 → 标准 `AUDIO`。
   - 连接方式：加载器 → 对应列表解析 → 生成或处理节点；单项解析按需使用。列表解析按有效素材顺序拆分，余下端口跳过执行。

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

With ComfyUI on `127.0.0.1:8188`, export the edited node schemas with
`tests/export_node_definitions.py` using ComfyUI's Python and its root on `PYTHONPATH`.
Serve this repository with `python -m http.server 8192 --bind 127.0.0.1`.
Run `tests/node_panels.browser.js` or `tests/media_loader.browser.js` as a Playwright
function with a `page` argument. These use isolated browser contexts to check layout,
both node renderers, restored selections, prompt serialization, fixed slots,
uploading, drag exchanges, and all three parser chains.

Run `tests/test_media_nodes.py -v` with the same Python environment for real image,
audio, and video parsing checks. Restart ComfyUI after updating the Python node files,
then refresh the browser with Ctrl+F5.
