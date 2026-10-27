"""Multi-object SAM orchestration; the installed native tracker owns inference."""
import json


def empty_ranges(present):
    ranges, start = [], None
    for i, value in enumerate(list(present) + [True]):
        if not value and start is None:
            start = i
        elif value and start is not None:
            ranges.append([start, i])
            start = None
    return ranges


def track_joint(count, people, anchors, run, decode):
    """Keep fixed object slots through correction intervals and reverse prefixes.

    Each run contains all objects. Packed native masks keep the complete result
    small; only boundary seeds are decoded at the prepared video resolution.
    """
    import torch
    first = [min(frame for frame, slot in anchors if slot == i) for i in range(people)]
    frames = sorted({frame for frame, _ in anchors})
    initial = torch.zeros_like(next(iter(anchors.values()))).expand(people, -1, -1).clone()

    def sweep(start, end, seeds):
        direction = 1 if end >= start else -1
        events = sorted([f for f in frames if min(start, end) <= f <= max(start, end)], reverse=direction < 0)
        boundaries = list(dict.fromkeys([start, *events, end]))
        output = None
        for j, frame in enumerate(boundaries):
            if j > 0 and j == len(boundaries) - 1 and frame not in frames:
                break
            for slot in range(people):
                if (frame, slot) in anchors:
                    seeds[slot] = anchors[frame, slot]
            stop = boundaries[j + 1] if j + 1 < len(boundaries) else end
            indices = list(range(frame, stop + direction, direction))
            packed = run(indices, seeds)
            if packed is None or packed.shape[:2] != (len(indices), people):
                raise ValueError("SAM 未返回完整的多人目标槽位，请检查模型与标记")
            packed = packed.cpu()
            if output is None:
                output = torch.zeros((count, *packed.shape[1:]), dtype=packed.dtype)
            output[indices] = packed
            seeds = decode(packed[-1]).clone()
        return output

    forward = sweep(min(first), count - 1, initial)
    # A later first annotation also describes earlier frames of that person.
    # Reverse all objects together; use that prefix only before each first mark.
    if max(first) > 0:
        backward = sweep(max(first), 0, decode(forward[max(first)]).clone())
        for slot, frame in enumerate(first):
            forward[:frame, slot] = backward[:frame, slot]
    return forward


def refine_box_anchor(model, image, anchor, negative):
    """Send the rectangle and optional correction points to the same SAM decoder."""
    import torch
    import torch.nn.functional as F
    import comfy.model_management as mm
    import comfy.utils
    mm.load_model_gpu(model)
    device, dtype = mm.get_torch_device(), model.model.get_dtype()
    h, w = image.shape[1:3]
    pixels = comfy.utils.common_upscale(image[..., :3].movedim(-1, 1), 1008, 1008,
                                       'bilinear', crop='disabled').to(device=device, dtype=dtype)
    x1, y1, x2, y2 = anchor['box']
    box = torch.tensor([[[x1/w*1008, y1/h*1008], [x2/w*1008, y2/h*1008]]], device=device, dtype=dtype)
    positive = anchor['positive']
    points = None
    if positive or negative:
        points = {'point_coords': torch.tensor([[[p['x']/w*1008, p['y']/h*1008]
                   for p in positive + negative]], device=device, dtype=dtype),
                  'point_labels': torch.tensor([[1]*len(positive) + [0]*len(negative)], device=device, dtype=torch.int32)}
    sam = model.model.diffusion_model
    logits = None
    for _ in range(2):
        logits = sam.forward_segment(pixels, box_inputs=box, point_inputs=points, mask_inputs=logits)
    return (F.interpolate(logits, size=(h, w), mode='bilinear', align_corners=False)[0, 0] > 0).float().cpu()


class YuanH3TrackPeople:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "images": ("IMAGE",),
            "source_frames": ("INT", {"min": 1}), "people_json": ("STRING", {})}}
    RETURN_TYPES = ("YUAN_H3_PERSON_TRACKS",)
    FUNCTION = "track"
    CATEGORY = "yton-nodes/H3"

    def track(self, model, images, source_frames, people_json):
        import torch
        import torch.nn.functional as F
        import nodes
        import comfy.model_management
        from comfy_extras.nodes_sam3 import SAM3_VideoTrack
        from comfy.ldm.sam3.tracker import unpack_masks
        people = json.loads(people_json)
        ids = [person["id"] for person in people]
        if not 1 <= len(ids) <= 6 or len(set(ids)) != len(ids):
            raise ValueError("追踪需要 1–6 个不同的人物 ID")
        if not 1 <= source_frames <= len(images):
            raise ValueError("追踪帧数与视频不一致")
        h, w = images.shape[1:3]
        anchors = {}
        for slot, person in enumerate(people):
            if not person["anchors"]:
                raise ValueError(f'{person["name"]} 尚未标记')
            for anchor in person["anchors"]:
                frame = anchor["frame"]
                if not 0 <= frame < source_frames or (not anchor["positive"] and "box" not in anchor):
                    raise ValueError("人物修正帧或包含点无效")
                # Other colors' positive marks on this same frame are exclusions.
                negative = list(anchor["negative"])
                for other in people:
                    if other["id"] != person["id"]:
                        for other_anchor in other["anchors"]:
                            if other_anchor["frame"] == frame:
                                negative.extend(other_anchor["positive"])
                with torch.inference_mode():
                    if 'box' in anchor:
                        mask = refine_box_anchor(model, images[frame:frame+1], anchor, negative)
                    else:
                        mask = nodes.NODE_CLASS_MAPPINGS["H3RelayRefineMask"]().refine(
                            model, images[frame:frame+1], json.dumps(anchor["positive"]),
                            json.dumps(negative), "", frame)[0][0]
                if not (mask > .5).any():
                    raise ValueError(f'{person["name"]} 在第 {frame + 1} 帧的标记未选中人物，请调整包含点')
                anchors[frame, slot] = mask.cpu()

        def run(indices, seeds):
            comfy.model_management.throw_exception_if_processing_interrupted()
            result = SAM3_VideoTrack.execute(images=images[indices], model=model,
                initial_mask=seeds, max_objects=len(people))[0]
            return result["packed_masks"]

        def decode(packed):
            return F.interpolate(unpack_masks(packed).float()[:, None],
                size=(h, w), mode="bilinear", align_corners=False)[:, 0]

        with torch.inference_mode():
            packed = track_joint(source_frames, len(people), anchors, run, decode)
        return ({"packed_masks": packed, "orig_size": (h, w), "n_frames": source_frames,
            "prepared_frames": len(images), "people": ids},)


class YuanH3TrackedPersonMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"tracks": ("YUAN_H3_PERSON_TRACKS",),
            "person_id": ("STRING", {}), "expansion_px": ("INT", {"min": 0, "max": 256})}}
    RETURN_TYPES = ("MASK", "MASK")
    RETURN_NAMES = ("raw_mask", "expanded_mask")
    FUNCTION = "select"
    CATEGORY = "yton-nodes/H3"

    def select(self, tracks, person_id, expansion_px):
        import numpy as np
        import torch
        from scipy.ndimage import distance_transform_edt
        from comfy_extras.nodes_sam3 import SAM3_TrackToMask
        slot = tracks["people"].index(person_id)
        raw = SAM3_TrackToMask.execute(tracks, str(slot))[0].cpu() > .5
        present = raw.flatten(1).any(1).tolist()
        if not any(present):
            raise ValueError(f"人物 {person_id} 全程没有有效蒙版，请重新标记")
        masks = raw.numpy()
        expanded = torch.from_numpy(np.stack([
            distance_transform_edt(~mask) <= expansion_px if expansion_px and mask.any() else mask
            for mask in masks]).astype(np.float16))
        if tracks["prepared_frames"] > len(expanded):
            expanded = torch.cat([expanded, expanded[-1:].expand(tracks["prepared_frames"] - len(expanded), -1, -1)])
        return {"result": (raw, expanded), "ui": {"empty_ranges": empty_ranges(present)}}


def tracked_mask_path(mask_file):
    from pathlib import Path
    import folder_paths
    root = Path(folder_paths.get_output_directory()).resolve()
    path = (root / mask_file).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != '.npz' or not path.is_file():
        raise ValueError('追踪蒙版必须是 ComfyUI output 目录中的 NPZ 文件')
    return path


class YuanH3LoadTrackedMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'mask_file': ('STRING', {}), 'images': ('IMAGE',),
            'source_frames': ('INT', {'default': 124, 'min': 1}),
            'expansion_px': ('INT', {'default': 16, 'min': 0, 'max': 256})}}
    RETURN_TYPES = ('MASK', 'MASK', 'STRING')
    FUNCTION = 'load'
    CATEGORY = 'yton-nodes/H3'

    @classmethod
    def IS_CHANGED(cls, mask_file, **kwargs):
        import hashlib
        with tracked_mask_path(mask_file).open('rb') as source:
            return hashlib.file_digest(source, 'sha256').hexdigest()

    def load(self, mask_file, images, source_frames, expansion_px):
        from pathlib import Path
        import shutil
        import tempfile
        import folder_paths
        import nodes
        source = tracked_mask_path(mask_file)
        root = Path(folder_paths.get_input_directory()).resolve()
        # H3 Relay only opens input files. Keep its validation and mask policies
        # intact, staging the reviewed output mask just for this load.
        with tempfile.TemporaryDirectory(dir=root, prefix='yuan-h3-mask-') as directory:
            target = Path(directory) / 'mask.npz'
            shutil.copyfile(source, target)
            expanded, raw, provenance = nodes.NODE_CLASS_MAPPINGS['H3RelayLoadMask']().load(
                target.relative_to(root).as_posix(), images, source_frames, expansion_px)
        provenance = json.loads(provenance)
        provenance['file'] = str(source)
        return expanded, raw, json.dumps(provenance)


NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in (YuanH3TrackPeople, YuanH3TrackedPersonMask, YuanH3LoadTrackedMask)}
NODE_DISPLAY_NAME_MAPPINGS = {"YuanH3TrackPeople": "H3 多人物联合追踪", "YuanH3TrackedPersonMask": "H3 按人物 ID 提取蒙版", "YuanH3LoadTrackedMask": "H3 加载追踪蒙版"}
