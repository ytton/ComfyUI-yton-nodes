import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

app.registerExtension({
  name: "yton.launcherGuard",
  async setup() {
    const response = await api.fetchApi("/yton/launcher-guard");
    if (!response.ok) {
      console.error("[yton] 无法读取本地模型联动设置", await response.text());
      return;
    }
    let config = await response.json();
    let writes = Promise.resolve();
    const update = (key, value) => {
      if (config[key] === value) return;
      writes = writes.then(async () => {
        const result = await api.fetchApi("/yton/launcher-guard", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [key]: value }),
        });
        if (!result.ok) throw new Error((await result.json()).error);
        config = await result.json();
      }).catch(error => {
        app.extensionManager.toast.add({ severity: "error", summary: "本地模型联动设置保存失败", detail: String(error), life: 8000 });
      });
    };
    for (const [key, name, type, tooltip] of [
      ["enabled", "执行工作流前卸载本地模型", "boolean", "全局生效，包含 API 工作流。立即中断本地推理并卸载模型，执行期间禁止自动唤醒；结束后清理 ComfyUI 模型缓存。"],
      ["baseUrl", "Qwen Launcher 地址", "text", "填写根地址，例如 http://127.0.0.1:8080，不加 /v1。开启联动后，启动器不可达会阻止工作流。"],
      ["waitSeconds", "等待本地模型卸载（秒）", "number", "确认模型进程退出的最长等待时间（10–1800 秒），不会等待已有推理自然完成。"],
    ]) {
      app.ui.settings.addSetting({
        id: `Yton.LauncherGuard.${key}`, name, type, tooltip,
        category: ["yton-nodes", "本地模型联动", name],
        defaultValue: config[key],
        onChange: value => update(key, value),
        ...(type === "number" ? { attrs: { min: 10, max: 1800, step: 10 } } : {}),
      });
    }
  },
});
