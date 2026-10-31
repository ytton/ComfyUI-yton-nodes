import { app } from "../../../scripts/app.js";

export function mountNodePanel(node, name, panel, minWidth, initialHeight, { fitHeight = false } = {}) {
  const shell = document.createElement("div");
  shell.className = "yton-widget-shell";
  shell.appendChild(panel);

  let contentHeight = initialHeight;
  const widget = node.addDOMWidget(name, "custom_ui", shell, {
    serialize: false,
    margin: 10,
    surfaces: { panel: "never" },
    getMinHeight: () => contentHeight + 20,
    getHeight: () => contentHeight + 20,
    ...(fitHeight ? { getMaxHeight: () => contentHeight + 20 } : {}),
  });
  widget.serialize = false;
  // The inspector writes its own width into legacy widgets when a node is
  // selected. This DOM panel must follow the node, not the inspector canvas.
  Object.defineProperty(widget, "width", {
    get: () => node.size[0],
    set: () => {},
  });

  function fitContent() {
    if (!panel.offsetHeight && fitHeight) return;
    if (panel.offsetHeight) contentHeight = panel.offsetHeight;
    const minimum = node.computeSize();
    const width = Math.max(node.size[0], minWidth);
    let height = fitHeight ? minimum[1] : Math.max(node.size[1], minimum[1]);
    if (fitHeight && app.canvas && !node.flags.collapsed) {
      // Vue computes its widget minimum independently of the socket rows.
      // Include the rendered panel's offset so the lower controls stay inside.
      const { ds, canvas } = app.canvas;
      const nodeTop = canvas.getBoundingClientRect().top + (node.pos[1] + ds.offset[1]) * ds.scale;
      height = Math.max(height, Math.ceil((panel.getBoundingClientRect().bottom - nodeTop) / ds.scale + 20));
    }
    if (width !== node.size[0] || height !== node.size[1]) {
      node.setSize([width, height]);
    }
    node.setDirtyCanvas(true, true);
  }

  const onResize = node.onResize;
  node.onResize = function (size) {
    onResize?.apply(this, arguments);
    size[0] = Math.max(size[0], minWidth);
    size[1] = Math.max(size[1], this.computeSize()[1]);
    if (fitHeight) scheduleFit();
  };
  let fitFrame;
  function scheduleFit() {
    cancelAnimationFrame(fitFrame);
    fitFrame = requestAnimationFrame(fitContent);
  }
  if (fitHeight) {
    const configure = node.onConfigure;
    node.onConfigure = function () {
      const result = configure?.apply(this, arguments);
      scheduleFit();
      return result;
    };
  }
  const observer = new ResizeObserver(scheduleFit);
  observer.observe(panel);
  const onRemoved = node.onRemoved;
  node.onRemoved = function () {
    observer.disconnect();
    cancelAnimationFrame(fitFrame);
    return onRemoved?.apply(this, arguments);
  };
  fitContent();
  return widget;
}
