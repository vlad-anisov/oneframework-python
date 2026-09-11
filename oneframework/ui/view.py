"""``View`` -- declarative UI plus transient state."""

from __future__ import annotations

from ..errors import DslError, did_you_mean
from ..model.expr import _RecordProxy, ViewFieldRef, map_refs
from ..model.fields import Field
from ..model.meta import ModelMeta
from .nodes import (
    DOCUMENT, FieldNode, ListNode, Node, ViewNode, _as_node, assign_ids,
)

__all__ = ["View", "ViewMeta", "build_ui", "document"]

class ViewMeta(type):
    def __new__(mcls, name, bases, ns, **kw):
        is_base = not any(isinstance(b, ViewMeta) for b in bases)
        cls = super().__new__(mcls, name, bases, dict(ns), **kw)
        cls._is_view = True

        if is_base:
            cls._model = None
            cls._state_fields = {}
            return cls

        # -- transient state fields (never become columns) -----------------
        state = {}
        declared = [(k, v) for k, v in ns.items() if isinstance(v, Field)]
        declared.sort(key=lambda kv: kv[1]._order)
        for key, field in declared:
            field.bind(cls, key)
            state[key] = field
        cls._state_fields = state

        model = ns.get("model", None)
        if model is not None and not isinstance(model, ModelMeta):
            raise DslError(
                f"View {name}: 'model' must be a Model class, got {model!r}."
            )
        cls._model = model
        # A model field called `title` must not be mistaken for the screen
        # title -- the field wins, and the class name is the fallback.
        declared = ns["_title"] if "_title" in ns else ns.get("title")
        cls._title = (
            declared if isinstance(declared, str) or callable(declared) else name
        )

        # -- presentation -------------------------------------------------- A
        # view no longer says how it arrives, because the same view honestly
        # wants both: Odoo's form is `current` from a list and `new` as a quick
        # create, and a property on the class forbids that and forces a twin.
        if "present" in ns:
            raise DslError(
                f"View {name}: 'present' is not a property of a view -- how a "
                f"screen arrives is said by whatever opens it:\n"
                f"    Create(<Model>, open={name}, target=\"sheet\")\n"
                f"    Open({name}, <record id>, target=\"sheet\")\n"
                f"so the same view can be a page in one place and a sheet in "
                f"another."
            )

        # -- leaving ---------------------------------------------------------
        # What the top-left control does and looks like.
        dismiss = ns.get("dismiss", "auto")
        if dismiss not in ("auto", "back", "close"):
            raise DslError(
                f"View {name}: dismiss={dismiss!r} is not valid; "
                "use 'auto', 'back' or 'close'."
            )
        cls._dismiss = dismiss

        # -- the path above
        # ---------------------------------------------------- Хлебные крошки
        # -- проекция стека, и правило рисует их само: цепочка существует, как
        # только кадров больше одного.
        crumbs = ns.get("crumbs", None)
        if crumbs not in (None, True, False):
            raise DslError(
                f"View {name}: crumbs={crumbs!r} is not valid; "
                "use True, False, or leave it out to let the rule decide."
            )
        cls._crumbs = crumbs

        # -- UI ---------------------------------------------------------------
        ui = ns.get("ui", None)
        if ui is not None and not callable(ui):
            raise DslError(
                f"View {name}: 'ui' is a method, not a value.\n"
                f"    class {name}(View):\n"
                f"        def ui(self, record):\n"
                f"            return {_rewrite_hint(ui)}\n"
                "Inside it a field of the record is 'record.<name>' and a field "
                "of the view is 'view.<name>'."
            )
        cls._ui_fn = ui
        return cls

    def __repr__(cls):
        return f"<View {cls.__name__}>"

def _rewrite_hint(ui):
    if isinstance(ui, (tuple, list)):
        return "(...)" if len(ui) != 1 else "(...,)"
    return f"{type(ui).__name__.replace('Node', '')}(...)"

def build_ui(view_cls, frame=None):
    fn = view_cls._ui_fn
    # `record` приезжает доводом, а не импортом.
    record = _RecordProxy(view_cls._model, f"View {view_cls.__name__}")
    node = assign_ids(
        ViewNode(view_cls, _normalize_ui(fn(frame, record) if fn else None,
                                         view_cls.__name__)),
        view_cls.__name__,
    )
    origin = f"View {view_cls.__name__}"
    _bind_state_fields(view_cls, node, origin)
    for child in node.children:
        child.bind(view_cls._model, origin)
    for n in node.walk():
        if isinstance(n, ListNode):
            n.validate()
            # `view.<name>` for a field the View never declared reads as UNSET
            # at query time, which drops the whole comparison and quietly shows
            # every record.
            for ref in _view_refs(n.domain):
                if ref not in view_cls._state_fields:
                    raise DslError(
                        f"{origin}: 'view.{ref}' in a List domain, but the view "
                        f"declares no such field."
                        + did_you_mean(ref, view_cls._state_fields)
                    )
    return node

def document(view_cls):
    """*view_cls* as a document: structure, references, conditions -- no data."""
    return build_ui(view_cls).ir(DOCUMENT)

def _bind_state_fields(view_cls, root, origin):
    """Resolve every ``view.<name>()`` drawn in the tree to its state field."""
    for node in root.walk():
        if isinstance(node, FieldNode) and isinstance(node.field, ViewFieldRef):
            name = node.field.name
            if name not in view_cls._state_fields:
                raise DslError(
                    f"Unknown view state 'view.{name}' in {origin}. Declare it on "
                    f"the View, e.g. '{name} = Boolean()'."
                    + did_you_mean(name, view_cls._state_fields)
                )
            node.field = view_cls._state_fields[name]

def _normalize_ui(ui, view_name):
    if ui is None:
        return []
    if isinstance(ui, Node):
        return [ui]
    if isinstance(ui, (tuple, list)):
        return [_as_node(c) for c in ui]
    raise DslError(
        f"View {view_name}: 'ui' must return a component or a tuple of "
        f"components, got {type(ui).__name__}."
    )

def _view_refs(domain):
    """Every ``view.<name>`` mentioned in a domain expression."""
    seen = []
    if domain is None:
        return seen

    def note(ref):
        if isinstance(ref, ViewFieldRef):
            seen.append(ref.name)
        return ref

    map_refs(domain, note)
    return seen

class View(metaclass=ViewMeta):
    _model = None
    _state_fields: dict[str, Field] = {}
    _ui_fn = None

