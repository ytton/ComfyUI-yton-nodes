export function mountNodePanel(node, name, panel, minWidth, initialHeight) {
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
  });
  widget.serialize = false;
  // The inspector writes its own width into legacy widgets when a node is
  // selected. This DOM panel must follow the node, not the inspector canvas.
  Object.defineProperty(widget, "width", {
    get: () => node.size[0],
    set: () => {},
  });

  function fitContent() {
    if (panel.offsetHeight) contentHeight = panel.offsetHeight;
    const minimum = node.computeSize();
    const width = Math.max(node.size[0], minWidth);
    const height = Math.max(node.size[1], minimum[1]);
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
  };
  const observer = new ResizeObserver(fitContent);
  observer.observe(panel);
  const onRemoved = node.onRemoved;
  node.onRemoved = function () {
    observer.disconnect();
    return onRemoved?.apply(this, arguments);
  };
  fitContent();
  return widget;
}
