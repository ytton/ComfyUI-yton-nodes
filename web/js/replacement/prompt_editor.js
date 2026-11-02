// Adapted from the locally installed PGS editor sources. See docs/CHARACTER_REPLACEMENT.md.
import {
  element,
  showAssetPopover,
  schedulePopoverHide,
} from "./prompt_editor_support.js";

export function tokensFromText(text, assets) {
  const assetMap = new Map(); assets.forEach(a => assetMap.set(a.alias.toLowerCase(), a));
  const aliases = [...assetMap.keys()].sort((a, b) => b.length - a.length)
    .map(alias => alias.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const known = aliases.length ? `[@＠](?:${aliases.join("|")})(?![A-Za-z0-9_-])|` : "";
  const pattern = new RegExp(`${known}[@＠][A-Za-z][A-Za-z0-9_-]{0,63}|<Picture\\s+\\d+>|<Video\\s+\\d+>|<Audio\\s+\\d+>|<Subject\\s+\\d+>|<\\/?d>`, "gi");
  const parts = []; let lastIndex = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index; if (index > lastIndex) parts.push({ type: "text", text: text.slice(lastIndex, index) });
    const raw = match[0]; const token = raw.startsWith("@") || raw.startsWith("＠") ? raw.slice(1) : raw; const lower = token.toLowerCase();
    if (raw.startsWith("@") || raw.startsWith("＠")) {
      const asset = assetMap.get(lower);
      if (asset) parts.push({ type: "reference", kind: asset.kind, text: raw, asset }); else parts.push({ type: "reference", kind: "unknown", text: raw, asset: null });
    } else if (/^<Subject/i.test(raw)) parts.push({ type: "subject", text: raw });
    else if (/^<\/?d>/i.test(raw)) parts.push({ type: "dialogue", text: raw });
    else {
      const kind = /^<Picture/i.test(raw) ? "image" : /^<Video/i.test(raw) ? "video" : "audio";
      const asset = assets.find(a => a.kind === kind && a.nativeLabel.toLowerCase() === raw.toLowerCase());
      parts.push({ type: "reference", kind, text: raw, asset: asset || null });
    }
    lastIndex = index + raw.length;
  }
  if (lastIndex < text.length) parts.push({ type: "text", text: text.slice(lastIndex) });
  return parts;
}

export function editorPlainText(editor) {
  function read(node, root) {
    if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
    if (node.nodeType === Node.DOCUMENT_FRAGMENT_NODE) return [...node.childNodes].map(child => read(child, root)).join("");
    if (node.nodeType !== Node.ELEMENT_NODE) return "";
    if (node.classList?.contains("yr-pgs-token")) return node.dataset.token ?? node.textContent ?? "";
    if (node.tagName === "BR") return "\n";
    let text = ""; for (const child of node.childNodes) text += read(child, root);
    if (["DIV", "P"].includes(node.tagName) && node !== root && !text.endsWith("\n")) text += "\n";
    return text;
  }
  return read(editor, editor).replace(/\n$/, "");
}

export function buildRichEditor({ initialText, assets, onInput, ownerGraph, resolveLabels = false, signal }) {
  if (!signal) signal = new AbortController().signal;
  const editor = element("div", "yr-pgs-rich-editor");
  editor.contentEditable = "true";
  editor.spellcheck = true;
  editor.dataset.placeholder = "输入提示词… 输入 @ 引用素材";
  let aliasMenu = null, aliasMenuItems = [], aliasMenuIndex = -1, aliasMenuAssets = [], aliasMenuCaretOffset = 0;

  function renderText(text, caret = null) {
    editor.innerHTML = "";
    const fragment = document.createDocumentFragment();
    const parts = tokensFromText(text, assets);
    for (const part of parts) {
      if (part.type === "text") { fragment.appendChild(document.createTextNode(part.text)); continue; }
      const tokenEl = element("span", `yr-pgs-token yr-pgs-token-${part.kind || "unknown"}`);
      tokenEl.contentEditable = "false";
      tokenEl.dataset.token = part.text;
      const displayText = (resolveLabels && part.asset) ? part.asset.nativeLabel : part.text;
      tokenEl.appendChild(element("span", "yr-pgs-token-dot"));
      tokenEl.appendChild(element("span", "yr-pgs-token-label", displayText));
      if (part.asset) {
        tokenEl.title = `@${part.asset.alias} → ${part.asset.nativeLabel}`;
        tokenEl.addEventListener("mouseenter", () => showAssetPopover(part.asset, tokenEl));
        tokenEl.addEventListener("mouseleave", schedulePopoverHide);
      }
      fragment.appendChild(tokenEl);
    }
    editor.appendChild(fragment);
    if (caret != null) restoreCaret(editor, caret);
  }

  function restoreCaret(node, offset) {
    const range = document.createRange(), selection = globalThis.getSelection?.();
    let consumed = 0, placed = false;
    function walk(current) {
      if (placed) return;
      if (current.nodeType === Node.TEXT_NODE) {
        const len = current.textContent?.length ?? 0;
        if (offset <= consumed + len) { range.setStart(current, Math.max(0, offset - consumed)); placed = true; return; }
        consumed += len; return;
      }
      if (current.nodeType !== Node.ELEMENT_NODE) return;
      if (current.classList?.contains("yr-pgs-token")) {
        const len = String(current.dataset.token ?? "").length;
        if (offset <= consumed + len) {
          if (offset <= consumed) range.setStartBefore(current);
          else range.setStartAfter(current);
          placed = true; return;
        }
        consumed += len; return;
      }
      for (const child of current.childNodes) walk(child);
    }
    walk(node);
    if (!placed) { range.selectNodeContents(node); range.collapse(false); } else range.collapse(true);
    selection?.removeAllRanges(); selection?.addRange(range);
  }

  function selectionTextOffset() {
    const selection = globalThis.getSelection?.();
    if (!selection?.rangeCount || !editor.contains(selection.anchorNode)) return editorPlainText(editor).length;
    const range = selection.getRangeAt(0).cloneRange();
    range.selectNodeContents(editor);
    range.setEnd(selection.anchorNode, selection.anchorOffset);
    return range.toString().length;
  }

  function insertPlainText(text) {
    const selection = globalThis.getSelection?.();
    const range = selection?.rangeCount && editor.contains(selection.anchorNode) ? selection.getRangeAt(0) : document.createRange();
    if (!selection?.rangeCount || !editor.contains(selection.anchorNode)) { range.selectNodeContents(editor); range.collapse(false); }
    range.deleteContents(); const textNode = document.createTextNode(text); range.insertNode(textNode); range.setStartAfter(textNode); range.collapse(true);
    selection?.removeAllRanges(); selection?.addRange(range); editor.dispatchEvent(new Event("input", { bubbles: true })); editor.focus();
  }

  function insertAlias(asset) {
    const textBefore = editorPlainText(editor);
    const caretBefore = aliasMenuCaretOffset != null ? aliasMenuCaretOffset : textBefore.length;
    restoreCaret(editor, caretBefore);
    const prefixChar = caretBefore > 0 ? textBefore.charAt(caretBefore - 1) : "";
    const needsAt = prefixChar !== "@" && prefixChar !== "＠";
    const insertText = needsAt ? `@${asset.alias}` : asset.alias;
    const selection = globalThis.getSelection?.();
    const range = selection?.rangeCount && editor.contains(selection.anchorNode) ? selection.getRangeAt(0) : document.createRange();
    if (!selection?.rangeCount || !editor.contains(selection.anchorNode)) { range.selectNodeContents(editor); range.collapse(false); }
    range.deleteContents(); const textNode = document.createTextNode(insertText); range.insertNode(textNode); range.setStartAfter(textNode); range.collapse(true);
    selection?.removeAllRanges(); selection?.addRange(range); editor.dispatchEvent(new Event("input", { bubbles: true }));
    const newText = editorPlainText(editor);
    const caretAfter = caretBefore + insertText.length;
    renderText(newText);
    restoreCaret(editor, Math.min(caretAfter, newText.length));
    editor.focus();
  }

  function insertDialogue() {
    editor.focus();
    const selection = globalThis.getSelection?.();
    const selected = selection?.rangeCount && editor.contains(selection.anchorNode) ? selection.toString() : "";
    insertPlainText(`<d>${selected}</d>`);
  }

  function closeAliasMenu() { if (aliasMenu) { aliasMenu.remove(); aliasMenu = null; } aliasMenuItems = []; aliasMenuIndex = -1; aliasMenuAssets = []; }

  function setAliasMenuIndex(index) {
    aliasMenuIndex = index;
    aliasMenuItems.forEach((item, i) => {
      item.classList.toggle("yr-pgs-alias-item-active", i === index);
      if (i === index) item.scrollIntoView({ block: "nearest" });
    });
  }

  function getCaretRect() {
    const selection = globalThis.getSelection?.();
    if (!selection || !selection.rangeCount || !editor.contains(selection.anchorNode)) return null;
    const range = selection.getRangeAt(0).cloneRange();
    let rect = range.getBoundingClientRect();
    if (!rect || (rect.width === 0 && rect.height === 0)) {
      const marker = document.createElement("span"); marker.textContent = "\u200B";
      range.insertNode(marker); rect = marker.getBoundingClientRect();
      marker.parentNode?.removeChild(marker); selection.removeAllRanges(); selection.addRange(range);
    }
    return rect;
  }

  function showAliasMenu(anchorRect = null) {
    aliasMenuCaretOffset = selectionTextOffset();
    closeAliasMenu();
    aliasMenuAssets = assets || [];
    const menu = element("div", "yr-pgs-alias-menu open");
    aliasMenu = menu;
    if (!aliasMenuAssets.length) {
      menu.appendChild(element("div", "yr-pgs-alias-item", "当前节点没有参考素材"));
      aliasMenuItems = []; aliasMenuIndex = -1;
    } else {
      aliasMenuItems = aliasMenuAssets.map((asset, index) => {
        const item = element("div", "yr-pgs-alias-item");
        const dot = element("span", `yr-pgs-token-dot yr-pgs-token-${asset.kind}`); dot.style.background = "currentColor";
        item.appendChild(dot);
        item.appendChild(document.createTextNode(`@${asset.alias} → ${asset.nativeLabel}`));
        item.addEventListener("mousedown", e => { e.preventDefault(); insertAlias(asset); closeAliasMenu(); });
        item.addEventListener("mouseenter", () => setAliasMenuIndex(index));
        menu.appendChild(item);
        return item;
      });
      setAliasMenuIndex(0);
      requestAnimationFrame(() => { if (aliasMenuItems.length) { aliasMenuItems[0].setAttribute("tabindex", "-1"); aliasMenuItems[0].focus(); } });
    }
    menu.tabIndex = -1;
    document.body.appendChild(menu);
    menu.style.visibility = "hidden";
    let caretRect = anchorRect || getCaretRect() || editor.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    let left = caretRect.left;
    let top = caretRect.bottom + 4;
    if (left + menuRect.width > window.innerWidth - 8) left = window.innerWidth - menuRect.width - 8;
    if (top + menuRect.height > window.innerHeight - 8) { top = caretRect.top - menuRect.height - 4; if (top < 8) top = 8; }
    left = Math.max(8, left); top = Math.max(8, top);
    menu.style.left = `${left}px`; menu.style.top = `${top}px`; menu.style.visibility = "visible";
  }

  function handleEditorKeydown(event) {
    if (!aliasMenu) {
      if ((event.key === "@" || event.key === "＠") && assets.length) {
        event.preventDefault(); event.stopPropagation();
        document.execCommand("insertText", false, "@");
        setTimeout(() => showAliasMenu(), 0);
        return;
      }
      return;
    }
    if (event.key === "ArrowDown") { event.preventDefault(); event.stopPropagation(); if (aliasMenuItems.length) setAliasMenuIndex(Math.min(aliasMenuItems.length - 1, aliasMenuIndex + 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); event.stopPropagation(); if (aliasMenuItems.length) setAliasMenuIndex(Math.max(0, aliasMenuIndex - 1)); }
    else if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); if (aliasMenuIndex >= 0) { insertAlias(aliasMenuAssets[aliasMenuIndex]); closeAliasMenu(); } }
    else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeAliasMenu(); }
  }

  editor.addEventListener("keydown", handleEditorKeydown);
  document.addEventListener("keydown", e => { if (!aliasMenu) return; if (["ArrowDown", "ArrowUp", "Enter", "Escape"].includes(e.key)) handleEditorKeydown(e); }, { capture: true, signal });
  editor.addEventListener("input", () => {
    const text = editorPlainText(editor);
    onInput(text);
    const caret = selectionTextOffset();
    const beforeCaret = text.slice(0, caret);
    if ((beforeCaret.endsWith("@") || beforeCaret.endsWith("＠")) && assets.length && !aliasMenu) showAliasMenu();
  });
  editor.addEventListener("blur", () => { if (aliasMenu) return; renderText(editorPlainText(editor)); closeAliasMenu(); });
  document.addEventListener("mousedown", e => { if (aliasMenu && !aliasMenu.contains(e.target)) closeAliasMenu(); }, { signal });
  renderText(initialText);
  return { editor, showAliasMenu, insertDialogue, getText: () => editorPlainText(editor), setText: t => renderText(t), focus: () => editor.focus(), dispose: () => { closeAliasMenu(); } };
}
