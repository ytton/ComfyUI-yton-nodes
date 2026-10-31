import { app } from "../../../scripts/app.js";

const TYPE = "YtonWeightedLoraLoader";
const ROW_HEIGHT = 30;
const strengthName = slot => `strengths.strength_${slot}`;

function setupLoraLoader(node) {
  const config = node.widgets.find(w => w.name === "loras");
  const names = node.constructor.nodeData.input.required.loras[1].yton_loras;
  // Rows own their socket lifetimes. Generic autogrow compacts disconnected
  // sockets, which would move a strength wire onto a different LoRA.
  delete node.comfyDynamic.autogrow.strengths;
  for (let i = node.inputs.length - 1; i >= 0; i--) {
    if (node.inputs[i].name.startsWith("strengths.")) node.removeInput(i);
  }
  Object.assign(config, { type: "hidden", hidden: true, computeSize: () => [0, -4],
    computeLayoutSize: () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 }) });
  config.options.hidden = true;
  let rows = [];

  function changed(resize = false) {
    config.value = JSON.stringify(rows);
    if (resize) node.setSize([Math.max(440, node.size[0]), node.computeSize()[1]]);
    node.graph?.change();
    node.setDirtyCanvas(true, true);
  }

  function chooseLora(event, select) {
    if (!names.length) {
      app.canvas.prompt("models/loras 中暂无 LoRA", "", () => {}, event);
      return;
    }
    const menu = new LiteGraph.ContextMenu(names, {
      event, title: "选择 LoRA", className: "dark",
      scale: Math.max(1, app.canvas.ds.scale),
      extra: { rgthree_doNotNest: true },
      callback: name => { select(name); changed(); },
    }, window);
    const filter = menu.root.querySelector(".comfy-context-menu-filter");
    if (filter) {
      filter.placeholder = "搜索 LoRA 文件名或目录";
      filter.setAttribute("aria-label", "搜索 LoRA");
    }
  }

  function removeRow(row) {
    node.graph?.beforeChange();
    node.removeInput(node.findInputSlot(strengthName(row.slot)));
    rows = rows.filter(item => item !== row);
    node.widgets = node.widgets.filter(w => w.name !== `lora_row_${row.slot}`);
    changed(true);
    node.graph?.afterChange();
  }

  function moveRow(row, index) {
    const previous = rows.indexOf(row);
    if (previous === index) return;
    node.graph?.beforeChange();
    rows.splice(previous, 1);
    rows.splice(index, 0, row);
    const widget = node.widgets.find(w => w.name === `lora_row_${row.slot}`);
    node.widgets.splice(node.widgets.indexOf(widget), 1);
    const next = rows[index + 1];
    const before = next ? node.widgets.find(w => w.name === `lora_row_${next.slot}`) : addButton;
    node.widgets.splice(node.widgets.indexOf(before), 0, widget);
    rows.forEach((item, i) => {
      node.inputs.find(input => input.name === strengthName(item.slot)).tooltip = `LoRA ${i + 1} 强度：${item.lora || "未选择"}`;
    });
    changed();
    node.graph?.afterChange();
  }

  function createRow(row, createSocket = true) {
    const name = `lora_row_${row.slot}`;
    if (createSocket) node.addInput(strengthName(row.slot), "FLOAT", {
      label: " ", widget: { name },
    });
    const input = node.inputs.find(i => i.name === strengthName(row.slot));
    input.label = " ";
    input.widget = { name };
    input.tooltip = `LoRA ${rows.indexOf(row) + 1} 强度：${row.lora || "未选择"}`;
    const widget = node.addCustomWidget({
      name, type: "yton_lora_row", value: row, serialize: false,
      options: { serialize: false, canvasOnly: true },
      computeSize: () => [440, ROW_HEIGHT],
      computeLayoutSize: () => ({ minHeight: ROW_HEIGHT, maxHeight: ROW_HEIGHT, minWidth: 440 }),
      draw(ctx, current, width, y) {
        this.rowY = y;
        const linked = input.link != null;
        const textColor = LiteGraph.WIDGET_TEXT_COLOR || "#ddd";
        ctx.save();
        const socket = current.getInputPos(current.findInputSlot(input.name));
        ctx.fillStyle = linked ? "#88a4cf" : (LiteGraph.NODE_DEFAULT_BGCOLOR || "#222");
        ctx.strokeStyle = "#88a4cf";
        ctx.beginPath(); ctx.arc(socket[0] - current.pos[0], socket[1] - current.pos[1], 4, 0, Math.PI * 2);
        ctx.fill(); ctx.stroke();
        ctx.fillStyle = LiteGraph.WIDGET_BGCOLOR || "#222";
        ctx.strokeStyle = LiteGraph.WIDGET_OUTLINE_COLOR || "#555";
        ctx.beginPath(); ctx.rect(15, y + 3, width - 30, ROW_HEIGHT - 6);
        ctx.fill(); ctx.stroke();
        ctx.globalAlpha = row.enabled ? 1 : 0.45;
        ctx.fillStyle = row.enabled ? "#88a4cf" : "#666";
        ctx.beginPath(); ctx.roundRect(22, y + 9, 27, 12, 6); ctx.fill();
        ctx.fillStyle = "#ddd";
        ctx.beginPath(); ctx.arc(row.enabled ? 42 : 29, y + 15, 7, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = textColor; ctx.font = "12px sans-serif";
        ctx.textAlign = "left";
        ctx.save(); ctx.beginPath(); ctx.rect(58, y, width - 206, ROW_HEIGHT); ctx.clip();
        let label = row.lora || "点击选择 LoRA";
        while (label.length > 1 && ctx.measureText(label).width > width - 212) label = label.slice(0, -1);
        if (label !== (row.lora || "点击选择 LoRA")) label += "…";
        ctx.fillText(label, 58, y + 19); ctx.restore();
        ctx.textAlign = "center";
        ctx.fillStyle = linked ? "#88a4cf" : textColor;
        ctx.fillText(linked ? "外部控制" : row.strength.toFixed(2), width - 89, y + 19);
        if (!linked) {
          ctx.fillText("◀", width - 132, y + 19);
          ctx.fillText("▶", width - 46, y + 19);
        }
        ctx.fillStyle = textColor; ctx.fillText("×", width - 22, y + 19);
        ctx.restore();
      },
      mouse(event, pos, current) {
        if (event.type !== "pointerdown" && event.type !== "mousedown") return false;
        if (event.button !== 0) return false;
        const x = pos[0], width = current.size[0];
        if (x < 18 || x > width - 12) return false;
        if (x < 54) { row.enabled = !row.enabled; changed(); }
        else if (x > width - 34) removeRow(row);
        else if (x < width - 146) chooseLora(event, name => { row.lora = name; input.tooltip = name; });
        else if (input.link == null) {
          if (x < width - 117 || x > width - 60) {
            row.strength = Math.round((row.strength + (x < width - 117 ? -0.05 : 0.05)) * 100) / 100;
            changed();
          } else app.canvas.prompt("LoRA 强度", String(row.strength), value => {
            const number = Number(value);
            if (value.trim() && Number.isFinite(number)) { row.strength = number; changed(); }
          }, event);
        }
        return true;
      },
    });
    node.widgets.splice(node.widgets.indexOf(widget), 1);
    node.widgets.splice(node.widgets.indexOf(addButton), 0, widget);
  }

  node.addWidget("button", "全部启用 / 关闭", null, () => {
    const enabled = !rows.every(row => row.enabled);
    rows.forEach(row => { row.enabled = enabled; }); changed();
  }, { serialize: false, canvasOnly: true });
  const addButton = node.addWidget("button", "＋ 添加 LoRA", null, (value, canvas, current, pos, event) => {
    chooseLora(event, lora => node.ytonAddLora(lora));
  }, { serialize: false, canvasOnly: true });

  node.ytonAddLora = function (lora = "") {
    const slot = Array.from({ length: 100 }, (_, i) => i).find(i => !rows.some(row => row.slot === i));
    if (slot === undefined) return;
    const row = { slot, enabled: true, lora, strength: 1 };
    rows.push(row); createRow(row); changed(true);
    return row;
  };
  node.ytonRemoveLora = slot => { const row = rows.find(row => row.slot === slot); if (row) removeRow(row); };

  const extraMenu = node.getExtraMenuOptions;
  node.getExtraMenuOptions = function (canvas, options) {
    const y = canvas.graph_mouse[1] - this.pos[1];
    const widget = this.widgets.find(w => w.type === "yton_lora_row" && y >= w.y && y < w.y + ROW_HEIGHT);
    if (!widget) return extraMenu?.apply(this, arguments);
    const row = rows.find(item => item.slot === widget.value.slot);
    const index = rows.indexOf(row);
    options.splice(0, options.length,
      { content: "上移", disabled: index === 0, callback: () => moveRow(row, index - 1) },
      { content: "下移", disabled: index === rows.length - 1, callback: () => moveRow(row, index + 1) },
      { content: "置顶", disabled: index === 0, callback: () => moveRow(row, 0) },
      { content: "置底", disabled: index === rows.length - 1, callback: () => moveRow(row, rows.length - 1) },
    );
  };

  const updateDisabled = node.updateComputedDisabled;
  node.updateComputedDisabled = function () {
    updateDisabled.apply(this, arguments);
    for (const widget of this.widgets.filter(w => w.type === "yton_lora_row")) {
      widget.connectionSuppressed = false;
      widget.disabled = false;
    }
  };
  const configure = node.onConfigure;
  node.onConfigure = function () {
    configure?.apply(this, arguments);
    rows = JSON.parse(config.value);
    node.widgets = node.widgets.filter(w => w.type !== "yton_lora_row");
    for (const row of rows) createRow(row, node.findInputSlot(strengthName(row.slot)) === -1);
    changed(true);
  };
  const connections = node.onConnectionsChange;
  node.onConnectionsChange = function () {
    connections?.apply(this, arguments);
    this.setDirtyCanvas(true, true);
  };
  node.setSize([500, node.computeSize()[1]]);
}

app.registerExtension({
  name: "yton.WeightedLoraLoader",
  nodeCreated(node) { if (node.comfyClass === TYPE) setupLoraLoader(node); },
});
