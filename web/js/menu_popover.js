export function attachMenuPopover(menu, options) {
  const summary = menu.querySelector("summary");
  summary.style.anchorName = `--yton-menu-${crypto.randomUUID()}`;
  summary.setAttribute("aria-expanded", "false");
  options.popover = "auto";
  options.style.positionAnchor = summary.style.anchorName;
  summary.addEventListener("click", event => {
    event.preventDefault();
    if (options.matches(":popover-open")) {
      options.hidePopover();
      menu.open = false;
    } else {
      menu.open = true;
      options.showPopover();
    }
  });
  options.addEventListener("toggle", () => {
    const open = options.matches(":popover-open");
    menu.open = open;
    summary.setAttribute("aria-expanded", String(open));
    if (open) document.addEventListener("wheel", scrollMenu, { capture: true, passive: true });
    else document.removeEventListener("wheel", scrollMenu, true);
  });
  menu.addEventListener("toggle", () => {
    if (!menu.open && options.matches(":popover-open")) options.hidePopover();
  });
  function scrollMenu(event) {
    // ComfyUI forwards wheel events from the widget shell to its canvas in capture phase.
    if (options.contains(event.target)) event.stopPropagation();
  }
  return () => {
    document.removeEventListener("wheel", scrollMenu, true);
    if (options.matches(":popover-open")) options.hidePopover();
  };
}
