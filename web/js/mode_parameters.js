import { app } from "../../../scripts/app.js";
import { mountNodePanel, followNodeColours } from "./node_panel.js";
import { commonComboChoices, comboTargets } from "./combo_options.js";

const TYPE = "YtonModeParameters";
const TYPES = [["STRING", "文本"], ["COMBO", "下拉选项（COMBO）"], ["FLOAT", "小数"], ["INT", "整数"], ["BOOLEAN", "布尔"]];
const DEFAULTS = { STRING: "", COMBO: "", FLOAT: 0, INT: 0, BOOLEAN: false };
const socketType = type => type === "STRING" ? "STRING,COMBO" : type;
const GEAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 3-.6 2.4-2 .9-2.2-.7L2 9.4l1.8 1.7v2L2 14.8l2.2 3.8 2.2-.7 2 .9L9 21h4l.6-2.2 2-.9 2.2.7 2.2-3.8-1.8-1.7v-2L20 9.4l-2.2-3.8-2.2.7-2-.9L13 3Z"/><circle cx="11" cy="12" r="3"/></svg>';
const style = document.createElement("link");
style.rel = "stylesheet";
style.href = new URL("../css/mode_parameters.css", import.meta.url).href;
document.head.append(style);

function el(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}
function button(text, action, className = "") {
  const item = el("button", className, text);
  item.type = "button";
  item.onclick = action;
  return item;
}
function input(value, label, onChange, type = "text") {
  const item = el("input");
  item.type = type;
  item.value = value;
  item.setAttribute("aria-label", label);
  item.oninput = () => onChange(item.value);
  return item;
}
function checkConfig(data) {
  if (!data.options.length) throw Error("至少添加一个 Option。");
  if (data.outputs.length > 64) throw Error("最多添加 64 个输出。");
  for (const [items, label] of [[data.options, "Option"], [data.outputs, "输出"]]) {
    const names = items.map(item => item.label.trim());
    if (names.some(name => !name)) throw Error(`${label}名称不能为空。`);
    if (new Set(names).size !== names.length) throw Error(`${label}名称不能重复。`);
  }
  for (const option of data.options) for (const field of data.outputs) {
    const value = data.values[option.id][field.id];
    const valid = field.type === "COMBO" ? typeof value === "string" || Number.isSafeInteger(value)
      : field.type === "STRING" ? typeof value === "string"
      : field.type === "BOOLEAN" ? typeof value === "boolean"
      : field.type === "INT" ? Number.isSafeInteger(value) : typeof value === "number" && Number.isFinite(value);
    if (!valid) throw Error(`「${option.label}」的「${field.label}」需要有效的${TYPES.find(t => t[0] === field.type)[1]}值。`);
  }
}

export function setupModeParameters(node) {
  node.properties.ytonModeLayout = { rows: 1, columns: 2 };
  const config = node.widgets.find(w => w.name === "config");
  const selected = node.widgets.find(w => w.name === "selected");
  for (const widget of [config, selected]) {
    Object.assign(widget, { type: "hidden", hidden: true, computeSize: () => [0, -4],
      computeLayoutSize: () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 }), draw() {} });
    widget.options.hidden = true;
  }
  let data = JSON.parse(config.value);
  let dialog;
  let updatingOutputs = false;
  const panel = el("div", "yton-mode-parameters");
  const segments = el("div", "yton-mode-segments");
  segments.setAttribute("role", "group");
  segments.setAttribute("aria-label", "模式");
  const footer = el("div", "yton-mode-footer");
  const settings = button(undefined, openSettings, "yton-mode-gear");
  settings.innerHTML = GEAR;
  settings.title = "模式配置";
  settings.setAttribute("aria-label", "模式配置");
  footer.append(settings);
  panel.append(segments, footer);

  function syncOutputs() {
    const wanted = [
      { id: "$mode", label: "模式", type: "STRING" },
      { id: "$index", label: "索引", type: "INT" },
      ...data.outputs,
    ];
    const previousIds = node.properties.ytonModeOutputIds || ["$mode", "$index"];
    const sameLayout = node.outputs.length === wanted.length && wanted.every((field, i) => previousIds[i] === field.id && node.outputs[i].type === socketType(field.type));
    if (!sameLayout) {
      updatingOutputs = true;
      const connections = node.outputs.flatMap((output, index) => (output.links || []).map(id => {
        const link = node.graph?.links[id];
        return link && { field: previousIds[index], type: output.type, target: link.target_id, slot: link.target_slot };
      }).filter(Boolean));
      // The current LiteGraph stores sockets by index. Reconnect by field ID
      // through its public API instead of sorting index-backed socket objects.
      while (node.outputs.length) node.removeOutput(node.outputs.length - 1);
      for (const field of wanted) node.addOutput(field.label, socketType(field.type), { label: field.label });
      for (const connection of connections) {
        const index = wanted.findIndex(field => field.id === connection.field && socketType(field.type) === socketType(connection.type));
        const target = node.graph?.getNodeById(connection.target);
        if (index >= 0 && target) node.connect(index, target, connection.slot);
      }
      updatingOutputs = false;
    }
    wanted.forEach((field, index) => {
      node.outputs[index].name = field.label;
      node.outputs[index].label = field.label;
    });
    node.properties.ytonModeOutputIds = wanted.map(field => field.id);
  }
  function render() {
    const { rows, columns } = node.properties.ytonModeLayout;
    segments.style.gridTemplateColumns = `repeat(${columns}, minmax(0, 1fr))`;
    segments.style.gridTemplateRows = `repeat(${Math.max(rows, Math.ceil(data.options.length / columns))}, minmax(34px, auto))`;
    segments.replaceChildren();
    for (const option of data.options) {
      const item = button(option.label, () => {
        if (selected.value === option.id) return;
        node.graph?.beforeChange();
        selected.value = option.id;
        render();
        selected.callback?.(selected.value);
        node.graph?.afterChange();
        node.graph?.change();
        node.setDirtyCanvas(true, true);
      });
      item.setAttribute("aria-pressed", String(selected.value === option.id));
      segments.append(item);
    }
  }
  function syncComboValues() {
    data.outputs.forEach((field, index) => {
      if (field.type !== "COMBO") return;
      const connections = comboTargets(node, index + 2);
      const values = commonComboChoices(connections);
      if (!values.length) return;
      const { target, input } = connections[0];
      const current = target.widgets?.find(w => w.name === input.widget?.name || w.name === input.name)?.value;
      for (const row of Object.values(data.values)) {
        if (!values.includes(row[field.id])) row[field.id] = values.includes(current) ? current : values[0];
      }
    });
    config.value = JSON.stringify(data);
  }
  function applyConfiguration(next, layout = node.properties.ytonModeLayout) {
    checkConfig(next);
    if (![layout.rows, layout.columns].every(value => Number.isSafeInteger(value) && value > 0)) throw Error("行数和列数需要填写大于 0 的整数。");
    node.graph?.beforeChange();
    node.properties.ytonModeLayout = { rows: Math.max(layout.rows, Math.ceil(next.options.length / layout.columns)), columns: layout.columns };
    data = structuredClone(next);
    for (const item of [...data.options, ...data.outputs]) item.label = item.label.trim();
    if (!data.options.some(option => option.id === selected.value)) selected.value = data.options[0].id;
    config.value = JSON.stringify(data);
    syncOutputs();
    syncComboValues();
    render();
    node.setSize([Math.max(340, node.size[0]), node.computeSize()[1]]);
    node.graph?.afterChange();
    node.graph?.change();
    node.setDirtyCanvas(true, true);
  }

  function openSettings() {
    if (dialog?.open) return;
    const draft = structuredClone(data);
    const draftLayout = { rows: node.properties.ytonModeLayout.rows, columns: node.properties.ytonModeLayout.columns };
    let activeStep = 0;
    let activeOption = draft.options[0].id;
    dialog = el("dialog", "yton-mode-dialog");
    const header = el("header");
    header.append(el("div", "yton-mode-heading", "模式配置"), button("×", () => dialog.close(), "yton-mode-close"));
    const tabs = el("nav", "yton-mode-steps");
    tabs.setAttribute("aria-label", "配置步骤");
    const body = el("div", "yton-mode-body");
    const error = el("div", "yton-mode-error");
    error.setAttribute("role", "alert");
    const actions = el("footer");
    const previous = button("上一步", () => { activeStep--; renderStep(); });
    const next = button("下一步", () => { activeStep++; renderStep(); });
    const save = button("保存配置", () => {
      try { applyConfiguration(draft, draftLayout); dialog.close(); }
      catch (e) { error.textContent = e.message; }
    }, "primary");
    actions.append(previous, el("span", "yton-mode-spacer"), button("取消", () => dialog.close()), next, save);
    dialog.append(header, tabs, body, error, actions);
    document.body.append(dialog);
    dialog.onclose = () => { dialog.remove(); dialog = undefined; };
    dialog.addEventListener("keydown", event => event.stopPropagation());
    dialog.addEventListener("pointerdown", event => event.stopPropagation());
    for (const [index, name] of ["Option", "输出", "参数值"].entries()) {
      const tab = button(`${index + 1}  ${name}`, () => { activeStep = index; renderStep(); });
      tabs.append(tab);
    }
    function move(items, index, amount) {
      [items[index], items[index + amount]] = [items[index + amount], items[index]];
      renderStep();
    }
    function rowActions(items, index, remove) {
      const tools = el("div", "yton-mode-row-actions");
      for (const [label, amount] of [["上移", -1], ["下移", 1]]) {
        const action = button(amount < 0 ? "↑" : "↓", () => move(items, index, amount));
        action.title = label;
        action.setAttribute("aria-label", label);
        action.disabled = index + amount < 0 || index + amount >= items.length;
        tools.append(action);
      }
      const del = button("×", remove);
      del.title = "删除";
      del.setAttribute("aria-label", "删除");
      tools.append(del);
      return tools;
    }
    function renderStep() {
      error.textContent = "";
      body.replaceChildren();
      [...tabs.children].forEach((tab, i) => tab.setAttribute("aria-current", String(i === activeStep)));
      previous.hidden = activeStep === 0;
      next.hidden = activeStep === 2;
      if (activeStep === 0) {
        body.append(el("h3", "", "设置模式选项"), el("p", "yton-mode-hint", "选项名称会显示在节点分段器中，同时作为模式字符串输出。索引按排列顺序从 0 开始。"));
        const layout = el("div", "yton-mode-layout-settings");
        layout.append(el("span", "", "节点排列"));
        for (const [key, title] of [["rows", "行数"], ["columns", "列数"]]) {
          if (key === "columns") layout.append(el("span", "yton-mode-layout-times", "×"));
          const label = el("label");
          const control = input(draftLayout[key], title, value => { draftLayout[key] = value.trim() ? Number(value) : null; }, "number");
          control.min = "1";
          control.step = "1";
          label.append(control, el("span", "", key === "rows" ? "行" : "列"));
          layout.append(label);
        }
        layout.title = "按行、列排列模式按钮；网格容量不足时自动补行，保证全部选项可见。";
        body.append(layout);
        draft.options.forEach((option, index) => {
          const row = el("div", "yton-mode-option-row");
          row.append(el("span", "yton-mode-index", String(index)), input(option.label, `Option ${index + 1} 名称`, value => { option.label = value; }), rowActions(draft.options, index, () => {
            if (draft.options.length === 1) { error.textContent = "至少保留一个 Option。"; return; }
            draft.options.splice(index, 1);
            delete draft.values[option.id];
            if (activeOption === option.id) activeOption = draft.options[0].id;
            renderStep();
          }));
          body.append(row);
        });
        body.append(button("＋ 添加 Option", () => {
          const option = { id: crypto.randomUUID(), label: `模式 ${draft.options.length + 1}` };
          draft.options.push(option);
          draft.values[option.id] = Object.fromEntries(draft.outputs.map(f => [f.id, DEFAULTS[f.type]]));
          renderStep();
        }, "yton-mode-add"));
      } else if (activeStep === 1) {
        body.append(el("h3", "", "定义共享输出"), el("p", "yton-mode-hint", "COMBO 连到目标后，可在参数值页选择目标的下拉选项。文本也可直连 STRING 和 COMBO。修改字段类型会断开现有连线。"));
        draft.outputs.forEach((field, index) => {
          const row = el("div", "yton-mode-field-row");
          const type = el("select");
          type.setAttribute("aria-label", `输出 ${index + 1} 类型`);
          for (const [value, label] of TYPES) { const option = el("option", "", label); option.value = value; type.append(option); }
          type.value = field.type;
          type.onchange = () => {
            field.type = type.value;
            for (const option of draft.options) draft.values[option.id][field.id] = DEFAULTS[field.type];
          };
          row.append(input(field.label, `输出 ${index + 1} 名称`, value => { field.label = value; }), type, rowActions(draft.outputs, index, () => {
            draft.outputs.splice(index, 1);
            for (const option of draft.options) delete draft.values[option.id][field.id];
            renderStep();
          }));
          body.append(row);
        });
        const add = button("＋ 添加输出", () => {
          const field = { id: crypto.randomUUID(), label: `参数 ${draft.outputs.length + 1}`, type: "STRING" };
          draft.outputs.push(field);
          for (const option of draft.options) draft.values[option.id][field.id] = "";
          renderStep();
        }, "yton-mode-add");
        add.disabled = draft.outputs.length >= 64;
        body.append(add);
      } else {
        body.append(el("h3", "", "分别设置每个模式的参数"));
        const layout = el("div", "yton-mode-values-layout");
        const choices = el("div", "yton-mode-value-options");
        for (const option of draft.options) {
          const item = button(option.label || "未命名", () => { activeOption = option.id; renderStep(); });
          item.setAttribute("aria-pressed", String(activeOption === option.id));
          choices.append(item);
        }
        const values = el("div", "yton-mode-values");
        if (!draft.outputs.length) values.append(el("p", "yton-mode-hint", "当前只输出模式字符串和索引。可在“输出”中添加参数字段。"));
        for (const field of draft.outputs) {
          const label = el("label", "yton-mode-value-field");
          const title = el("span", "yton-mode-value-label", field.label || "未命名");
          title.append(el("small", "", TYPES.find(t => t[0] === field.type)[1]));
          let control;
          const value = draft.values[activeOption][field.id];
          if (field.type === "COMBO") {
            const slot = data.outputs.findIndex(item => item.id === field.id);
            const choices = slot < 0 ? [] : commonComboChoices(comboTargets(node, slot + 2));
            control = el("select");
            control.disabled = !choices.length;
            if (!choices.length) control.append(el("option", "", "先保存配置并连接到目标下拉输入"));
            choices.forEach((choice, index) => {
              const option = el("option", "", String(choice));
              option.value = String(index);
              control.append(option);
            });
            control.value = String(Math.max(0, choices.indexOf(value)));
            control.onchange = () => { draft.values[activeOption][field.id] = choices[Number(control.value)]; };
          } else if (field.type === "STRING") {
            control = el("textarea");
            control.rows = 4;
            control.value = value;
            control.oninput = () => { draft.values[activeOption][field.id] = control.value; };
          } else if (field.type === "BOOLEAN") {
            control = el("input"); control.type = "checkbox"; control.checked = value;
            control.onchange = () => { draft.values[activeOption][field.id] = control.checked; };
          } else {
            control = input(value ?? "", field.label, text => { draft.values[activeOption][field.id] = text.trim() ? Number(text) : null; }, "number");
            control.step = field.type === "INT" ? "1" : "any";
          }
          control.setAttribute("aria-label", field.label || "未命名输出");
          label.append(title, control);
          values.append(label);
        }
        layout.append(choices, values);
        body.append(layout);
      }
    }
    renderStep();
    dialog.showModal();
  }

  node.ytonModeParameters = { configure: applyConfiguration, openSettings, getConfig: () => structuredClone(data), syncComboValues };
  const connect = node.onConnectOutput;
  node.onConnectOutput = function (slot, type, input, target) {
    if (data.outputs[slot - 2]?.type === "COMBO" && !commonComboChoices([...comboTargets(this, slot), { target, input }]).length) return false;
    return connect?.apply(this, arguments);
  };
  const connections = node.onConnectionsChange;
  node.onConnectionsChange = function (side) {
    const result = connections?.apply(this, arguments);
    if (side === LiteGraph.OUTPUT && !updatingOutputs) syncComboValues();
    return result;
  };
  const configure = node.onConfigure;
  node.onConfigure = function () {
    configure?.apply(this, arguments);
    data = JSON.parse(config.value);
    syncOutputs(); render();
  };
  const removed = node.onRemoved;
  node.onRemoved = function () { dialog?.close(); return removed?.apply(this, arguments); };
  syncOutputs();
  render();
  followNodeColours(node, panel);
  mountNodePanel(node, "mode_parameters_ui", panel, 340, 78, { fitHeight: true });
  panel.parentElement.classList.add("yton-mode-shell");
  node.setSize([340, node.computeSize()[1]]);
}

app.registerExtension({
  name: "yton.ModeParameters",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== TYPE) return;
    // Previews render the definition without creating a node. Keep reserved
    // execution slots out of the frontend definition as well as the canvas.
    for (const key of ["output", "output_name", "output_is_list", "output_tooltips"]) {
      nodeData[key] = nodeData[key].slice(0, 2);
    }
    nodeData.output[0] = socketType("STRING");
    for (const name of ["config", "selected"]) nodeData.input.required[name][1].hidden = true;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = created?.apply(this, arguments);
      setupModeParameters(this);
      return result;
    };
  },
  afterConfigureGraph() {
    for (const node of app.graph._nodes) node.ytonModeParameters?.syncComboValues();
  },
});
