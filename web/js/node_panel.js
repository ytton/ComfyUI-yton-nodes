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

export function followNodeColours(node, panel) {
  function sync() {
    panel.style.setProperty("--yton-node-bg", node.bgcolor || LiteGraph.NODE_DEFAULT_BGCOLOR);
    panel.style.setProperty("--yton-node-fg", node.title_text_color || LiteGraph.NODE_TEXT_COLOR);
  }
  // Vue nodes do not run the canvas drawing hook. Colour edits must update
  // the DOM panel when the native palette writes the node's colour fields.
  for (const name of ["bgcolor", "title_text_color"]) {
    let owner = node;
    let descriptor;
    while (owner && !descriptor) {
      descriptor = Object.getOwnPropertyDescriptor(owner, name);
      owner = Object.getPrototypeOf(owner);
    }
    let value = node[name];
    Object.defineProperty(node, name, {
      configurable: true,
      enumerable: true,
      get() { return descriptor?.get ? descriptor.get.call(this) : value; },
      set(next) {
        if (descriptor?.set) descriptor.set.call(this, next);
        else value = next;
        sync();
      },
    });
  }
  for (const hook of ["onConfigure", "onDrawBackground"]) {
    const previous = node[hook];
    node[hook] = function () {
      const result = previous?.apply(this, arguments);
      sync();
      return result;
    };
  }
  sync();
}
