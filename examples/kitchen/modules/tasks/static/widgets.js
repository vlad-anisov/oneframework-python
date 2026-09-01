// A module's own widget, registered under "<field type>:<widget>" -- the same
// convention the built-ins use, so `state(widget="pill")` works in the DSL with
// no framework change. The file is discovered because it sits in static/.
oneframework.registerWidget("selection:pill", {
  create(node) {
    const el = document.createElement("span");
    el.className = "tasks-pill";
    this.update(el, node);
    return el;
  },
  update(el, node) {
    const choice = (node.choices || []).find((c) => c.value === node.value);
    el.textContent = choice ? choice.label : "—";
    el.dataset.state = node.value || "";
  },
});
