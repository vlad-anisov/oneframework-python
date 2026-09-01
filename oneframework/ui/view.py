"""``View`` -- declarative UI plus transient state.

A view describes its screen with one method::

    class TodoLineItem(View):
        model = TodoLine

        def ui(self, record):
            return Row(
                record.sequence(widget="handle"),
                record.text(widget="title"),
                Button(icon="delete", action=Delete()),
            )

``ui`` is a method and nothing else. It is ordinary Python -- a comprehension
over records is a repeater, an ``if`` is a conditional -- and every name in it
is a name Python (and a linter) can see: ``record.<field>`` for a column of the
record being drawn, ``view.<field>`` for the screen's own transient state.

The tree is therefore a fact about the *data*, not about the class, and it is
built once per render inside the screen's effect: whatever the method reads is
what re-runs it. The cost is that DSL mistakes -- an unknown field, a widget a
field does not offer, a ``List`` whose item view is bound to another model --
surface when the screen opens rather than at import. :func:`build_ui` runs the
same checks the class body used to run, so the message is the same one.
"""

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

        # -- bound model ---------------------------------------------------
        model = ns.get("model", None)
        if model is not None and not isinstance(model, ModelMeta):
            raise DslError(
                f"View {name}: 'model' must be a Model class, got {model!r}."
            )
        cls._model = model
        # A model field called `title` must not be mistaken for the screen
        # title -- the field wins, and the class name is the fallback.
        # `_title` is the way to say it when the model has a field called
        # `title`. An empty one is a screen that deliberately shows none -- how
        # both platforms write a record card, where the record is on the page
        # already and repeating its name in the bar says nothing.
        declared = ns["_title"] if "_title" in ns else ns.get("title")
        cls._title = (
            declared if isinstance(declared, str) or callable(declared) else name
        )

        # -- presentation --------------------------------------------------
        # A view no longer says how it arrives, because the same view honestly
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
        # What the top-left control does and looks like. A screen holding a
        # draft is a piece of work, finished or abandoned, and both platforms
        # mark that with a close glyph rather than an arrow -- but a screen that
        # merely happens to be new is still a step in a journey, so the default
        # is a default and not a rule.
        dismiss = ns.get("dismiss", "auto")
        if dismiss not in ("auto", "back", "close"):
            raise DslError(
                f"View {name}: dismiss={dismiss!r} is not valid; "
                "use 'auto', 'back' or 'close'."
            )
        cls._dismiss = dismiss

        # -- the path above ----------------------------------------------------
        # Хлебные крошки -- проекция стека, и правило рисует их само: цепочка
        # существует, как только кадров больше одного. Но «существует» и «стоит
        # яруса» -- не одно и то же: в приложении глубиной в два кадра первое
        # звено повторяет стрелку «назад», стоящую в том же баре, и платить за
        # это шестьюдесятью четырьмя пикселями незачем. Поэтому у экрана есть
        # право сказать иначе, а у правила остаётся умолчание.
        #
        #   не сказано -- решает правило: широкое окно и кадров больше одного;
        #   False      -- не показывать здесь никогда;
        #   True       -- показывать и на телефоне тоже, если цепочка есть.
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
    """The old value, written the way the method should return it."""
    if isinstance(ui, (tuple, list)):
        return "(...)" if len(ui) != 1 else "(...,)"
    return f"{type(ui).__name__.replace('Node', '')}(...)"


def build_ui(view_cls, frame=None):
    """The tree of *view_cls*, built and checked for this render.

    *frame* is the screen the tree is being drawn on, and it is what ``ui``
    receives as ``self``: a list item view is drawn many times over on one
    screen, so it gets that screen rather than a frame of its own.

    Without one the result is the *document*: the same tree, built for nobody in
    particular. A view that reads ``self`` cannot give one, and that is the
    whole of the difference between a view that is data and a view that is still
    a program.
    """
    fn = view_cls._ui_fn
    # `record` приезжает доводом, а не импортом. Разница не в наборе букв:
    # импортированное имя ниоткуда не видно в сигнатуре, и на вопрос «откуда
    # оно здесь взялось» ответить, читая метод, нельзя. Довод отвечает сам.
    #
    # `self` при этом остаётся экраном, а не записью, и это не оговорка: один
    # вид строки рисует сотню записей, у экрана же своё состояние -- строка
    # поиска, выбранная вкладка. Свести их в одно имя значило бы соврать про
    # список.
    # Привязан к модели вида -- поэтому `record.summary()` знает, что это
    # метод, а не поле, а опечатка отказывает здесь же, с подсказкой.
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
            # every record. Catch the typo here instead.
            for ref in _view_refs(n.domain):
                if ref not in view_cls._state_fields:
                    raise DslError(
                        f"{origin}: 'view.{ref}' in a List domain, but the view "
                        f"declares no such field."
                        + did_you_mean(ref, view_cls._state_fields)
                    )
    return node


def document(view_cls):
    """*view_cls* as a document: structure, references, conditions -- no data.

    The thing this whole design turns on. A ``ui`` method run against a screen
    yields a tree of *answers*: this record's title, these five boards, this
    count. Run against nobody it yields the questions instead -- ``{"i": "name"}``
    where the name goes, ``{"agg": "count"}`` where the number goes, a
    ``repeat`` where the five boards were -- and that is a thing worth storing,
    fingerprinting and sending, because it changes when the app changes and not
    when the data does.

    :func:`oneframework.ui.expand.expand` is the other half: document plus data back
    into a tree.

    Строится с ``ctx=DOCUMENT``: снимок несёт разрешённые значения, документ --
    объявления, и это два разных артефакта. Домен списка, порядок сортировки и
    цель действия существуют только здесь -- на проводе их нет и быть не должно,
    потому что там всё это уже отвечено.
    """
    return build_ui(view_cls).ir(DOCUMENT)


def _bind_state_fields(view_cls, root, origin):
    """Resolve every ``view.<name>()`` drawn in the tree to its state field.

    Only the ones being *rendered*: ``view.tag`` inside a domain stays a
    reference, because its value is read from live screen state per query.
    """
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
    """Declarative UI. Bind it to a record with ``model = <Model>``.

    Fields declared on a View are transient state and never create a column.
    """

    _model = None
    _state_fields: dict[str, Field] = {}
    _ui_fn = None

    @classmethod
    def state_defaults(cls):
        """Initial transient state. Unset state is :data:`UNSET`, not ``None``."""
        from ..model.expr import UNSET

        return {name: UNSET for name in cls._state_fields}
