export const PATH_TAGS = [
  ["date", "日期"], ["time", "时间"], ["datetime", "日期时间"], ["index", "序号"],
  ["resolution", "分辨率"], ["width", "宽度"], ["height", "高度"], ["fps", "帧率"],
  ["frames", "帧数"], ["duration", "时长"], ["year", "年"], ["month", "月"], ["day", "日"],
];
const labels = new Map(PATH_TAGS);

export function createPathEditor(value, onChange) {
  const root = document.createElement("div");
  root.className = "yton-video-path";
  const editor = document.createElement("div");
  editor.className = "yton-video-path-input";
  editor.contentEditable = "true";
  editor.spellcheck = false;
  editor.setAttribute("role", "textbox");
  editor.setAttribute("aria-label", "保存路径");
  editor.setAttribute("aria-multiline", "false");
  editor.title = "相对于 ComfyUI/output，点击下方标签可在光标处插入";
  const tags = document.createElement("div");
  tags.className = "yton-video-path-tags";
  root.append(editor, tags);
  let bookmark;

  function fragment(text) {
    const result = document.createDocumentFragment();
    for (const part of String(text).split(/(\{[a-z]+\})/g)) {
      const token = part.slice(1, -1);
      if (part.startsWith("{") && labels.has(token)) {
        const chip = document.createElement("span");
        chip.className = "yton-video-path-chip";
        chip.contentEditable = "false";
        chip.dataset.token = token;
        chip.textContent = labels.get(token);
        chip.title = part;
        result.append(chip);
      } else {
        result.append(document.createTextNode(part));
      }
    }
    return result;
  }

  function getValue() {
    function text(node) {
      if (node.nodeType === Node.TEXT_NODE) return node.textContent;
      if (node.dataset?.token) return `{${node.dataset.token}}`;
      return [...node.childNodes].map(text).join("");
    }
    return text(editor);
  }

  function remember() {
    const selection = window.getSelection();
    if (selection.rangeCount && editor.contains(selection.anchorNode) && editor.contains(selection.focusNode)) {
      bookmark = selection.getRangeAt(0).cloneRange();
    }
  }

  function insert(text) {
    editor.focus();
    const selection = window.getSelection();
    const range = bookmark && editor.contains(bookmark.startContainer) ? bookmark : document.createRange();
    if (range !== bookmark) {
      range.selectNodeContents(editor);
      range.collapse(false);
    }
    range.deleteContents();
    const content = fragment(text);
    const caret = document.createTextNode("");
    content.append(caret);
    range.insertNode(content);
    range.setStartAfter(caret);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    remember();
    onChange(getValue());
  }

  for (const [token, label] of PATH_TAGS) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.title = `插入${label}标签 {${token}}`;
    button.addEventListener("mousedown", event => event.preventDefault());
    button.addEventListener("click", () => insert(`{${token}}`));
    tags.append(button);
  }
  editor.addEventListener("input", () => { remember(); onChange(getValue()); });
  editor.addEventListener("keyup", remember);
  editor.addEventListener("mouseup", remember);
  editor.addEventListener("focusout", remember);
  editor.addEventListener("keydown", event => {
    if (event.key === "Enter") event.preventDefault();
    event.stopPropagation();
  });
  editor.addEventListener("paste", event => {
    event.preventDefault();
    remember();
    insert(event.clipboardData.getData("text/plain").replace(/[\r\n]/g, ""));
  });
  function copySelection(event) {
    const selection = window.getSelection();
    if (!selection.rangeCount || selection.isCollapsed) return false;
    const clone = document.createElement("div");
    clone.append(selection.getRangeAt(0).cloneContents());
    for (const chip of clone.querySelectorAll("[data-token]")) chip.replaceWith(`{${chip.dataset.token}}`);
    event.clipboardData.setData("text/plain", clone.textContent);
    event.preventDefault();
    return true;
  }
  editor.addEventListener("copy", copySelection);
  editor.addEventListener("cut", event => {
    if (!copySelection(event)) return;
    window.getSelection().getRangeAt(0).deleteContents();
    remember();
    onChange(getValue());
  });
  function setValue(next) {
    editor.replaceChildren(fragment(next ?? ""));
    bookmark = null;
  }
  setValue(value);
  return { root, editor, getValue, setValue };
}
