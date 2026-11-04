import { request } from "../replacement_common.js";

export function createShotControls(host, onChange) {
    const controls = {};
    const detailLabels = [];
    const add = (key, title, options, value) => {
        const label = document.createElement("label");
        label.style.cssText = "display:flex;align-items:center;gap:5px;color:#b8d2dc;font-size:11px;";
        label.append(document.createTextNode(title + ":"));
        const control = document.createElement(options ? "select" : "input");
        control.setAttribute("aria-label", title);
        control.style.cssText = "background:#223744;color:#dce7ee;border:1px solid #3a5363;border-radius:4px;padding:3px 6px;font-size:11px;max-width:150px;";
        if (options) {
            for (const [value, text] of options) control.add(new Option(text, value));
        } else {
            control.type = "number";
            control.min = "0";
            control.step = "0.1";
            control.style.width = "64px";
        }
        control.value = value;
        control.onchange = () => { sync(); onChange(); };
        label.append(control);
        host.append(label);
        controls[key] = control;
        if (key !== "split") detailLabels.push(label);
    };
    add("split", "切分方式", [["fixed", "固定段长"], ["shots", "按镜头切分"]], "fixed");
    add("detector", "镜头检测", [["adaptive", "自适应（推荐）"], ["content", "画面差异"]], "adaptive");
    add("sensitivity", "灵敏度", null, .5);
    controls.sensitivity.max = "1";
    controls.sensitivity.step = "0.05";
    add("min_seconds", "最短镜头（秒）", null, 1);
    controls.min_seconds.title = "过短镜头可与相邻镜头合并；合并后仍不超过最长段长。";
    function sync() {
        for (const label of detailLabels) label.style.display = controls.split.value === "shots" ? "flex" : "none";
    }
    sync();
    return {
        read: () => ({split: controls.split.value, detector: controls.detector.value,
            sensitivity: Number(controls.sensitivity.value), min_seconds: Number(controls.min_seconds.value)}),
        restore(settings) {
            for (const key of Object.keys(controls)) if (settings[key] !== undefined) controls[key].value = settings[key];
            sync();
        },
    };
}

export function requestShotPlan(video, settings) {
    return request("replacement/shot-plan", {video, settings});
}
