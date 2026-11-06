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
    let text = "";
    for (const child of node.childNodes) {
      if (["DIV", "P"].includes(child.nodeName) && text && !text.endsWith("\n")) text += "\n";
      text += read(child, root);
    }
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
  let aliasMenu = null, aliasMenuItems = [], aliasMenuIndex = -1, aliasMenuAssets = [], aliasMenuRange = null;

  function tokenElement(part) {
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
    return tokenEl;
  }

  function renderText(text) {
    editor.innerHTML = "";
    const fragment = document.createDocumentFragment();
    const parts = tokensFromText(text, assets);
    for (const part of parts) {
      if (part.type === "text") { fragment.appendChild(document.createTextNode(part.text)); continue; }
      fragment.appendChild(tokenElement(part));
    }
    editor.appendChild(fragment);
  }

  function selectedRange() {
    const selection = globalThis.getSelection?.();
    if (selection?.rangeCount && editor.contains(selection.anchorNode) && editor.contains(selection.focusNode)) return selection.getRangeAt(0).cloneRange();
    const range = document.createRange();
    range.selectNodeContents(editor); range.collapse(false);
    return range;
  }

  function insertPlainText(text) {
    const selection = globalThis.getSelection?.();
    const range = selectedRange();
    range.deleteContents(); const textNode = document.createTextNode(text); range.insertNode(textNode); range.setStartAfter(textNode); range.collapse(true);
    selection?.removeAllRanges(); selection?.addRange(range); editor.dispatchEvent(new Event("input", { bubbles: true })); editor.focus();
  }

  function insertAlias(asset) {
    const selection = globalThis.getSelection?.();
    const range = aliasMenuRange.cloneRange();
    const token = tokenElement({kind:asset.kind, text:`@${asset.alias}`, asset});
    const textNode = document.createTextNode("");
    const fragment = document.createDocumentFragment(); fragment.append(token, textNode);
    range.deleteContents(); range.insertNode(fragment); range.setStart(textNode, 0); range.collapse(true);
    closeAliasMenu();
    editor.focus({preventScroll:true});
    selection?.removeAllRanges(); selection?.addRange(range);
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function insertDialogue() {
    editor.focus();
    const selection = globalThis.getSelection?.();
    const selected = selection?.rangeCount && editor.contains(selection.anchorNode) ? selection.toString() : "";
    insertPlainText(`<d>${selected}</d>`);
  }

  function closeAliasMenu() { if (aliasMenu) { aliasMenu.remove(); aliasMenu = null; } aliasMenuItems = []; aliasMenuIndex = -1; aliasMenuAssets = []; aliasMenuRange = null; }

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
    const rect = range.getBoundingClientRect();
    return rect.width || rect.height ? rect : null;
  }

  function showAliasMenu(anchorRect = null) {
    closeAliasMenu();
    aliasMenuRange = selectedRange();
    const {startContainer, startOffset} = aliasMenuRange;
    if (aliasMenuRange.collapsed && startContainer.nodeType === Node.TEXT_NODE && /[@＠]/.test(startContainer.textContent.charAt(startOffset - 1))) {
      aliasMenuRange.setStart(startContainer, startOffset - 1);
    }
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
        item.addEventListener("mousedown", e => { e.preventDefault(); insertAlias(asset); });
        item.addEventListener("mouseenter", () => setAliasMenuIndex(index));
        menu.appendChild(item);
        return item;
      });
      setAliasMenuIndex(0);
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
    if (!aliasMenu || event.isComposing) return;
    if (event.key === "ArrowDown") { event.preventDefault(); event.stopPropagation(); if (aliasMenuItems.length) setAliasMenuIndex(Math.min(aliasMenuItems.length - 1, aliasMenuIndex + 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); event.stopPropagation(); if (aliasMenuItems.length) setAliasMenuIndex(Math.max(0, aliasMenuIndex - 1)); }
    else if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); if (aliasMenuIndex >= 0) insertAlias(aliasMenuAssets[aliasMenuIndex]); }
    else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeAliasMenu(); }
    else if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) closeAliasMenu();
  }

  editor.addEventListener("keydown", handleEditorKeydown);
  editor.addEventListener("input", event => {
    const text = editorPlainText(editor);
    onInput(text);
    if (event.isComposing) return;
    const range = selectedRange();
    const {startContainer, startOffset} = range;
    if (range.collapsed && startContainer.nodeType === Node.TEXT_NODE && /[@＠]/.test(startContainer.textContent.charAt(startOffset - 1)) && assets.length) showAliasMenu();
    else closeAliasMenu();
  });
  editor.addEventListener("blur", () => { closeAliasMenu(); renderText(editorPlainText(editor)); });
  document.addEventListener("mousedown", e => { if (aliasMenu && !aliasMenu.contains(e.target)) closeAliasMenu(); }, { signal });
  renderText(initialText);
  return { editor, showAliasMenu, insertDialogue, getText: () => editorPlainText(editor), setText: t => renderText(t), focus: () => editor.focus(), dispose: () => { closeAliasMenu(); } };
}
