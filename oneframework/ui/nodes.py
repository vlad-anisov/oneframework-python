"""Component IR.

The Python DSL never emits HTML. It builds a tree of these nodes, and
:meth:`Node.ir` serialises that tree to plain JSON dicts. Any renderer able to
read the IR can drive the UI -- today a Framework7/DOM renderer, tomorrow an
XML-authored view or a different toolkit.

Node kinds: ``view row field list button search filter sort action``.
"""

from __future__ import annotations

from ..errors import DslError, did_you_mean
from ..model.expr import (
    Expr, ItemFieldRef, Order, RecordFieldRef, Ref,
    iter_refs, map_refs, parse_template,
)
# Imported here rather than inside the methods that use it: the browser host
# snapshots the interpreter once everything is imported and then throws the
# filesystem away, so a module first imported while the app is drawing exists on
# the cold start and is gone on every warm one.
from ..model.exprjson import to_json
from ..model.fields import Field

__all__ = [
    "Node",
    "ViewNode",
    "RowNode",
    "ColNode",
    "GroupNode",
    "SectionNode",
    "PillNode",
    "TextNode",
    "TabsNode",
    "TabNode",
    "FieldNode",
    "ListNode",
    "ButtonNode",
    "SearchNode",
    "FilterNode",
    "SortNode",
    "Action",
    "DeleteAction",
    "OpenAction",
    "CreateAction",
    "SetAction",
    "SaveAction",
    "bind_node",
]

#: field types a table right-aligns, the way every data grid does...
_NUMERIC_TYPES = frozenset(
    {"integer", "float", "monetary", "percent", "duration", "rating"}
)
#: ...but only when the cell is the number itself. A stepper or a row of stars
#: is a control, and controls line up on the left like everything else.
_NUMERIC_WIDGETS = frozenset({"number", "monetary", "percent", "duration"})


class Node:
    """Base IR node.

    ``_nid`` is derived from the shape of the tree, so the same structure gets
    the same ids on every render and they can key runtime state.
    """

    node_type = "node"
    _nid = None
    #: When this node is drawn: ``True``/``False`` outright, or a domain
    #: expression over ``record.<field>`` answered per record. Odoo's
    #: ``invisible`` is the precedent -- there too the condition is written on
    #: the field and evaluated against the record, which is what lets one row
    #: definition serve rows that differ.
    visible = True

    def ir(self, ctx=None):  # pragma: no cover - overridden
        raise NotImplementedError


    def _bind_visible(self, model, origin):
        self.visible = _bind_condition(self.visible, model, origin)

    def bind(self, model, origin):
        """Resolve any ``record.<name>`` inside this node against *model*."""
        return self

    def walk(self):
        yield self


#: Кому строится ir. Снимок и документ -- два разных артефакта, а не две версии
#: одного: снимок несёт разрешённые значения («вот эти строки»), документ --
#: объявления («вот по какому домену их брать»). Поэтому объявления едут только
#: при ``ctx=DOCUMENT``, а провод остаётся ровно таким, каким его закрепляет
#: ``protocol/wire.json``.
DOCUMENT = "document"


def _declares(ctx):
    return ctx == DOCUMENT


def _named(value):
    """Класс модели или вида едет в документ именем, а не объектом."""
    return getattr(value, "__name__", value) if value is not None else None


def _text_ir(value):
    """Текст узла так, как он едет в документе.

    Обычная строка едет собой. Шаблон со ссылками -- своим деревом: он ещё не
    строка, подставлять в него нечего, пока документ не развёрнут на данных.
    Развёрнутое дерево несёт здесь только строки, потому что разворот их и
    складывает -- рендерер про шаблоны не знает и знать не должен.
    """
    if value is None or isinstance(value, str):
        return value
    return to_json(value)


def _condition_ir(value):
    """``visible=`` / ``enabled=`` так, как они едут в документе.

    Ответ, если он уже есть, и само условие, если ответа ещё нет: в документе
    условие обязано сохраниться целиком, иначе шаблон, разложенный на две
    машины, значит на них разное.
    """
    if isinstance(value, bool):
        return value
    return to_json(value)


def _bind_ref(ref, model, origin):
    """Turn ``record.<name>`` into the real :class:`Field` of *model*.

    ``record.`` says "a column of whatever row is being drawn here", and only
    the enclosing ``List`` or ``View`` knows which model that is -- arguments
    are evaluated before the call that gives them their context.
    """
    if isinstance(ref, RecordFieldRef):
        if model is None:
            raise DslError(
                f"'record.{ref.name}' in {origin} has no model to resolve against. "
                "Set 'model = <Model>' on the View, or use it inside List(<Model>, ...)."
            )
        if ref.name not in model._fields:
            raise DslError(
                f"Unknown field 'record.{ref.name}' in {origin}."
                + did_you_mean(ref.name, model._fields)
            )
        return model._fields[ref.name]
    return ref


def _bind_condition(value, model, origin):
    """``visible=`` / ``enabled=``: a plain answer, or a condition to resolve.

    ``record.`` binds to a column of *model*; ``view.`` and ``item.`` stay
    references, because the screen state and the row of a repeat are read where
    they live and not from the model this node is about.
    """
    if isinstance(value, bool):
        return value
    return bind_node(value, model, origin)


def bind_node(node, model, origin):
    """Bind an expression tree / order term / node against *model*."""
    if isinstance(node, Node):
        return node.bind(model, origin)
    if node is None:
        return None
    return map_refs(node, lambda r: _bind_ref(r, model, origin))


# --------------------------------------------------------------------------
# structural nodes
# --------------------------------------------------------------------------
class ViewNode(Node):
    node_type = "view"

    def __init__(self, view_cls, children):
        self.view_cls = view_cls
        self.children = list(children)

    def ir(self, ctx=None):
        data = {
            "type": "view",
            "name": self.view_cls.__name__,
            "model": getattr(getattr(self.view_cls, "_model", None), "__name__", None),
            "children": [c.ir(ctx) for c in self.children],
        }
        if _declares(ctx):
            from ..model.schema import field_schema

            title = getattr(self.view_cls, "_title", None)
            # Заголовок-функция -- это вид, который ещё программа, как и вид,
            # читающий `self`. Документ такого заголовка не несёт, и молчать об
            # этом нельзя: тогда экран уехал бы без имени и никто бы не понял,
            # почему. Отмечаем прямо, и переезд остаётся видимым.
            data["title"] = None if callable(title) else title
            data["title_is_code"] = callable(title)
            data["dismiss"] = getattr(self.view_cls, "_dismiss", "auto")
            data["crumbs"] = getattr(self.view_cls, "_crumbs", None)
            # Состояние экрана -- поля, которые никогда не станут колонкой.
            # Без них рантайм не знает ни их типов, ни даже того, что они есть:
            # `view.tag`, упомянутый только в домене, в дереве не появляется.
            data["state"] = [
                field_schema(f)
                for f in sorted(
                    getattr(self.view_cls, "_state_fields", {}).values(),
                    key=lambda f: f._order,
                )
            ]
        return data

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class RepeatNode(Node):
    """One body, drawn once per record of a model.

    This is what a Python ``for`` over records becomes. The difference is not
    style but lifetime: a comprehension in ``ui()`` bakes the records that
    existed when the tree was built, so a list created afterwards never gets a
    tab. A repeat stays a question about the data, so the same document draws
    whatever is there.

    Inside the body the current record is ``item.<field>``; ``record.<field>``
    keeps meaning "the row being tested here", which is a different record --
    a List inside a Repeat filters ``record.board == item.id``.

    Precedent: ``t-foreach`` in QWeb and ``<repeat nodeset=...>`` in XForms.
    Odoo's form views have no such thing, because there the repetition that
    matters is the list itself -- which is why most loops do not need this node
    at all. Reach for it only when the *structure* comes from data, as tabs
    from boards do.
    """

    node_type = "repeat"

    def __init__(self, model, *children, domain=None, order=None):
        self.model = model
        self.children = [_as_node(c) for c in children]
        self.domain = domain
        self.order = order

    def ir(self, ctx=None):
        out = {
            "type": "repeat",
            "id": self._nid,
            "model": getattr(self.model, "__name__", self.model),
            "children": [c.ir(ctx) for c in self.children],
        }
        if self.domain is not None:
            out["domain"] = to_json(self.domain)
        if self.order is not None:
            out["order"] = to_json(self.order)
        return out

    def bind(self, model, origin):
        """``item.`` resolves against *our* model, ``record.`` against the outer one.

        The body is bound against the enclosing model, not ours, because a List
        inside still describes rows of its own model. Only ``item.`` belongs to
        the repeat, and it is checked here so a typo fails at build time rather
        than drawing an empty tab.
        """
        where = f"{origin} -> Repeat({getattr(self.model, '__name__', self.model)})"
        for node in self.walk():
            for ref in iter_refs(getattr(node, "visible", None)):
                self._check_item(ref, where)
        if self.domain is not None:
            self.domain = bind_node(self.domain, self.model, where)
        for c in self.children:
            c.bind(model, origin)
        return self

    def _check_item(self, ref, where):
        if not isinstance(ref, ItemFieldRef):
            return
        fields = getattr(self.model, "_fields", {})
        if fields and ref.name not in fields:
            raise DslError(
                f"Unknown field 'item.{ref.name}' in {where}."
                + did_you_mean(ref.name, fields)
            )

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class RowNode(Node):
    """Layout for a single record. Not a query -- see :class:`ListNode`."""

    node_type = "row"

    def __init__(self, *children):
        self.children = [_as_node(c) for c in children]

    def ir(self, ctx=None):
        return {
            "type": "row",
            "id": self._nid,
            "children": [c.ir(ctx) for c in self.children],
        }

    def bind(self, model, origin):
        for c in self.children:
            c.bind(model, origin)
        return self

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class MenuNode(Node):
    """An overflow menu, behind three dots.

    Given to ``List(menu=...)`` it belongs to that list and sits in its header.
    Put in a view with ``place="navbar"`` it belongs to the record instead and
    sits in the top bar -- which is where both platforms keep the actions on a
    record that are too rare, or too final, to earn a control of their own.
    """

    node_type = "menu"

    def __init__(self, *children, place=None, icon=None):
        self.children = [_as_node(c) for c in children]
        if place not in (None, "navbar", "navbar-left"):
            raise DslError(
                f"Menu(place={place!r}) is not valid; use 'navbar' or 'navbar-left'."
            )
        self.place = place
        #: The glyph of the link that opens it. Three dots is what an overflow
        #: menu looks like on both platforms, and it is a default, not a rule.
        self.icon = icon or "more_vert"

    def ir(self, ctx=None):
        return {
            "type": "menu",
            "id": self._nid,
            "place": self.place,
            "icon": self.icon,
            "children": [c.ir(ctx) for c in self.children],
        }

    def bind(self, model, origin):
        for c in self.children:
            c.bind(model, origin)
        return self

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class ColNode(Node):
    """Vertical stack. The default direction of a form, made explicit."""

    node_type = "col"

    def __init__(self, *children, span=None):
        self.children = [_as_node(c) for c in children]
        #: width in twelfths when this column sits inside a Row
        self.span = span

    def ir(self, ctx=None):
        return {
            "type": "col",
            "id": self._nid,
            "span": self.span,
            "children": [c.ir(ctx) for c in self.children],
        }

    def bind(self, model, origin):
        for c in self.children:
            c.bind(model, origin)
        return self

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class SectionNode(Node):
    """A heading between groups of fields."""

    node_type = "section"

    def __init__(self, title, subtitle=None):
        self.title = title
        self.subtitle = subtitle

    def ir(self, ctx=None):
        return {
            "type": "section",
            "id": self._nid,
            "title": self.title,
            "subtitle": self.subtitle,
        }


#: What a group is drawn on. ``"card"`` is a surface laid *on* the page --
#: inset from its edges, corners rounded, which is what a section of a form is
#: on both platforms and what every group has always been. ``"sheet"`` says the
#: group is not on the page but *is* it: the surface runs edge to edge and down
#: to the bottom, the way a full-screen record reads on Android. The same word
#: :data:`TARGETS` uses, for the same reason -- there it is a screen that
#: arrives as a sheet, here it is a section drawn as one.
GROUP_SURFACES = ("card", "sheet")


class GroupNode(Node):
    """Odoo's ``<group>``: a titled block of fields.

    ``cols`` lays the children out in that many columns on wide screens; on a
    phone a group is always a single column.

    ``surface`` chooses between the two containers Material gives a section --
    see :data:`GROUP_SURFACES`.
    """

    node_type = "group"

    def __init__(self, *children, label=None, cols=1, surface="card"):
        if surface not in GROUP_SURFACES:
            raise ValueError(
                f"Group(surface={surface!r}): expected one of "
                + ", ".join(repr(s) for s in GROUP_SURFACES)
            )
        self.children = [_as_node(c) for c in children]
        self.label = label
        self.cols = cols
        self.surface = surface

    def ir(self, ctx=None):
        return {
            "type": "group",
            "id": self._nid,
            "label": self.label,
            "cols": self.cols,
            "surface": self.surface,
            "children": [c.ir(ctx) for c in self.children],
        }

    def bind(self, model, origin):
        for c in self.children:
            c.bind(model, origin)
        return self

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class AccordionNode(Node):
    """A titled block that collapses -- Framework7's Accordion.

    The same shape as :class:`GroupNode`, but the user can fold it away.
    ``open`` decides whether it starts expanded.

    ``visible=`` is the one condition a *section* takes, and it is answered
    when the document is expanded rather than per record: "Выполненные" is a
    block that should not be on the screen at all while nothing is finished,
    which is a question about the data behind the block -- ``Exists(...)`` --
    and not about a row inside it. A section that fails it is not drawn hidden;
    it is simply not in the tree, exactly as the Python ``if`` that used to
    stand here left it out.
    """

    node_type = "accordion"

    def __init__(self, *children, label=None, open=False, visible=True):
        self.children = [_as_node(c) for c in children]
        self.label = label
        self.open = open
        self.visible = visible

    def ir(self, ctx=None):
        data = {
            "type": "accordion",
            "id": self._nid,
            "label": self.label,
            "open": bool(self.open),
            "children": [c.ir(ctx) for c in self.children],
        }
        if self.visible is not True:
            data["visible"] = _condition_ir(self.visible)
        return data

    def bind(self, model, origin):
        for c in self.children:
            c.bind(model, origin)
        return self

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class PillNode(Node):
    """A count beside a label -- ``Tab("Работа", Pill(3))``.

    Not a Material badge: that one is an alert, drawn in the error colour and
    anchored over its corner. This is part of the line it sits in, and it takes
    room there, which is how a tab strip shows how much is behind each tab.
    """

    node_type = "pill"

    #: When the pill is worth showing.
    #:   "always" -- whenever it has a value
    #:   "closed" -- only while the tab it labels is *not* the open one, where
    #:               the page below already says how much there is
    WHENS = ("always", "closed")

    def __init__(self, value, when="always"):
        if when not in self.WHENS:
            raise DslError(
                f"Pill(when={when!r}) is not valid."
                + did_you_mean(when, self.WHENS)
                + f" Valid values: {', '.join(self.WHENS)}."
            )
        #: A number, or the question that answers to one -- ``Count(Task, ...)``.
        #: The question is what a document carries; the number arrives with the
        #: data, when the document is expanded.
        self.value = value
        self.when = when

    def ir(self, ctx=None):
        value = self.value
        if isinstance(value, (Expr, Ref)):
            shown = _text_ir(value)
        elif value is None or value is False or value == 0:
            # Nothing to count is nothing to show: a zero badge is a mark on a
            # tab that says "empty", which both platforms leave off entirely.
            shown = None
        else:
            shown = str(value)
        return {
            "type": "pill",
            "id": self._nid,
            "value": shown,
            "when": self.when,
        }

    def bind(self, model, origin):
        return self


class TextNode(Node):
    """A plain piece of text in a title.

    ``"{item.name}"`` makes it a template rather than a constant -- see
    :func:`oneframework.model.expr.parse_template`.
    """

    node_type = "text"

    def __init__(self, value):
        self.value = parse_template(value)

    def ir(self, ctx=None):
        value = self.value
        if value is None or isinstance(value, (str, int, float)):
            return {"type": "text", "id": self._nid, "value": str(value)}
        return {"type": "text", "id": self._nid, "value": _text_ir(value)}

    def bind(self, model, origin):
        return self


class IconNode(Node):
    """A glyph where a piece of text would go -- ``Tab(Icon("star"), ...)``.

    A tab whose name is a picture says so with a glyph, not with a character
    that happens to look like one: a text star is set in the body font, at the
    body size, and lands wherever that font's designer put it, while everything
    beside it is a 24dp icon on the platform's grid.

    ``name`` is a Material Icons ligature, the same vocabulary ``Button(icon=)``
    uses -- there is one icon set in the build and this is a part of a title
    drawn from it.
    """

    node_type = "icon"

    def __init__(self, name):
        self.name = str(name)

    def ir(self, ctx=None):
        return {"type": "icon", "id": self._nid, "name": self.name}

    def bind(self, model, origin):
        return self


class TabNode(Node):
    """One page of a :class:`TabsNode` -- Odoo's ``<page>``.

    The title is whatever ``Text``, ``Icon`` and ``Pill`` parts are handed to
    it, laid out in a line; a bare string is shorthand for one ``Text``. So a
    tab that counts what is behind it says so itself::

        Tab("Работа", Pill(3, when="closed"), List(...))

    and one named by a picture rather than by a word says that::

        Tab(Icon("star"), List(...))

    rather than the strip being told to draw counts or glyphs and deciding for
    itself when they are wanted. None of ``Text``, ``Icon`` or ``Pill`` is page
    content, so which argument is which needs no marking.
    """

    node_type = "tab"

    #: The parts a title is made of, as opposed to the tab's contents.
    TITLE_PARTS = (TextNode, IconNode, PillNode)

    def __init__(self, label, *children):
        title = [TextNode(label)] if isinstance(label, str) else [_as_node(label)]
        content = []
        #: The floating action of this page. It hangs over the whole screen
        #: rather than sitting in the page, and which page is open is the one
        #: thing only the renderer knows -- so it is sorted out here, the way
        #: the title parts are, instead of being content the tab happens to
        #: hold.
        fab = None
        for c in children:
            node = _as_node(c)
            if isinstance(node, ButtonNode) and node.place == "fab":
                fab = node
            elif isinstance(node, self.TITLE_PARTS):
                title.append(node)
            else:
                content.append(node)
        self.title = title
        self.fab = fab
        #: The first text of the title, for anything that needs a plain name.
        #: A tab named by a glyph has none, and says so with an empty string
        #: rather than with the glyph's ligature, which is not a word.
        self.label = next((t.value for t in title if isinstance(t, TextNode)), "")
        self.children = content

    def ir(self, ctx=None):
        return {
            "type": "tab",
            "id": self._nid,
            "label": _text_ir(self.label),
            "title": [t.ir(ctx) for t in self.title],
            "fab": self.fab.ir(ctx) if self.fab is not None else None,
            "children": [c.ir(ctx) for c in self.children],
        }

    def bind(self, model, origin):
        if self.fab is not None:
            self.fab.bind(model, origin)
        for c in self.children:
            c.bind(model, origin)
        return self

    def walk(self):
        yield self
        # The title parts are nodes too, and they need ids like any other.
        yield from self.title
        if self.fab is not None:
            yield from self.fab.walk()
        for c in self.children:
            yield from c.walk()


class TabsNode(Node):
    """Odoo's ``<notebook>``: several pages, one visible at a time."""

    node_type = "tabs"

    #: Whether the tabs *are* the screen.
    #:   "auto" -- they are, when they are all the screen holds
    #:   True   -- always: each page scrolls on its own and swipes sideways
    #:   False  -- never: a control among others, scrolling with the page
    PAGES = ("auto", True, False)

    def __init__(self, *tabs, page="auto"):
        for tab in tabs:
            if not isinstance(tab, (TabNode, ButtonNode, RepeatNode)):
                raise DslError(
                    "Tabs(...) accepts Tab(...) pages, a Repeat(...) of them, and "
                    "a Button(...) to sit at the end of the strip; got "
                    f"{type(tab).__name__}."
                )
        if page not in self.PAGES:
            raise DslError(
                f"Tabs(page={page!r}) is not valid; use 'auto', True or False."
            )
        self.page = page
        self.children = list(tabs)

    def ir(self, ctx=None):
        return {
            "type": "tabs",
            "id": self._nid,
            "page": self.page,
            "children": [c.ir(ctx) for c in self.children],
        }

    def bind(self, model, origin):
        for c in self.children:
            c.bind(model, origin)
        return self

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class FieldNode(Node):
    """One field rendered with a semantic widget."""

    node_type = "field"

    def __init__(self, field, widget=None, label=None, visible=True, place=None,
                 placeholder=None, **options):
        self.field = field
        self.widget = widget
        self.label = label
        #: Text inside the empty control. Given one, the row shows no label line
        #: of its own -- the placeholder *is* the label, which is how both
        #: platforms write a form of optional additions ("Add a date"). Without
        #: one the label keeps its line and the control stays empty.
        self.placeholder = placeholder
        #: ``visible=False`` is declared but never drawn: the field still counts
        #: for everything the DSL reads off the tree -- an undrawn
        #: ``widget="handle"`` still makes its list reorderable -- it simply
        #: takes no room. A condition instead is answered per record, which is
        #: what lets one row definition serve rows that differ.
        self.visible = visible
        #: ``place="navbar"`` puts the control in the top bar rather than in the
        #: body. A one-tap property of the whole record -- starred, pinned,
        #: archived -- lives there on both platforms, beside the title instead
        #: of at the bottom of a form.
        #: Let a long value run onto further lines instead of being clipped.
        #: Framework7 keeps a row one line high, which is right for a table and
        #: wrong for a list of things people write sentences into.
        #: ``place="after"`` makes this the cell pinned to the end of its Row.
        #: Without one, the cell after the title takes that job.
        if place not in (None, "navbar", "navbar-left", "after"):
            raise DslError(
                f"Field(place={place!r}) is not valid; "
                "use 'navbar', 'navbar-left' or 'after'."
            )
        self.place = place
        self.options = options

    @property
    def field_name(self):
        return self.field.ref_name

    def bind(self, model, origin):
        self.field = _bind_ref(self.field, model, origin)
        self._bind_visible(model, origin)
        self._validate_widget(origin)
        return self

    def _validate_widget(self, origin):
        if self.widget is None or not isinstance(self.field, Field):
            return
        if self.widget not in self.field.widgets:
            raise DslError(
                f"Widget {self.widget!r} is not valid for "
                f"{type(self.field).__name__} field {self.field.name!r} in {origin}."
                + did_you_mean(self.widget, self.field.widgets)
                + f" Valid widgets: {', '.join(sorted(self.field.widgets))}."
            )

    def ir(self, ctx=None):
        f = self.field
        if not isinstance(f, Field):
            raise DslError(
                f"Field reference {f.ref_name!r} was never bound to a model."
            )
        owner = f.owner
        scope = "view" if getattr(owner, "_is_view", False) else "record"
        data = {
            "type": "field",
            "id": self._nid,
            "name": f.name,
            "scope": scope,
            "ftype": f.ftype,
            "widget": self.widget or f.default_widget,
            "label": self.label if self.label is not None else f.display_label,
            "required": bool(f.required),
            "readonly": bool(getattr(f, "readonly", False)),
            # The condition as written; a render that has a record replaces it
            # with the answer that record gives.
            "visible": _condition_ir(self.visible),
            "place": self.place,
            "placeholder": self.placeholder,
            "options": self.options,
        }
        # Type-specific metadata the renderer needs, contributed by the field
        # itself so adding a field type never means touching this method.
        for attr in ("currency", "digits", "maximum", "accept", "max_size", "inverse",
                     "unit", "semantic", "lines", "unique", "create"):
            if hasattr(f, attr):
                data["options"].setdefault(attr, getattr(f, attr))
        if f.ftype == "selection":
            data["choices"] = f.choices

        comodel = getattr(f, "comodel", None)
        if comodel is not None:
            co = f.resolve_comodel()
            df = co.display_field()
            color = next((x for x in co._fields.values() if x.ftype == "color"), None)
            data["comodel"] = {
                "name": co.__name__,
                "label": co._label,
                "display_field": df.name if df else None,
                "color_field": color.name if color else None,
            }
        return data


class ButtonNode(Node):
    """UI affordance. The behaviour lives in its :class:`Action`."""

    node_type = "button"

    def __init__(self, label=None, icon=None, action=None, style=None, place=None,
                 enabled=True, visible=True):
        if action is None:
            raise DslError(
                "Button(...) requires an action, e.g. Button(icon='trash', action=Delete())."
            )
        # Метод модели -- сам себе действие: `action=Note.summary`. Обёртка
        # `Logic(...)` при ссылке ничего не добавляла, а лишнее слово между
        # кнопкой и тем, что она делает, читается как обряд. Обёртка осталась
        # для случая, когда действию передают доводы или оно закрывает экран.
        if hasattr(action, "declaration") and hasattr(action, "writes"):
            action = LogicAction(action)
        if not isinstance(action, Action):
            raise DslError(
                f"Button action must be an Action instance, got {type(action).__name__}."
            )
        self.label = label
        self.icon = icon
        self.action = action
        #: Drawn outright, never, or per record -- see :attr:`Node.visible`. A
        #: row's controls are the case: the button a finished record offers is
        #: not the one an unfinished record offers.
        self.visible = visible
        #: A button the screen still offers but cannot act on right now. Both
        #: platforms grey it in place rather than removing it, so the menu keeps
        #: the same shape and the entry stays findable.
        #:
        #: A condition rather than a value when the answer belongs to the data:
        #: ``enabled=Exists(...)`` for "there is something to remove",
        #: ``enabled=record.title`` for "this record has been named". Written as
        #: a value it would be answered when the tree was built and stay wrong
        #: for as long as the screen is up.
        self.enabled = enabled if isinstance(enabled, (Expr, Ref)) else bool(enabled)
        #: ``"plain"`` is a labelled action with no fill -- a word you press.
        #: Both platforms use it where a filled button would be too loud for
        #: what it does: inside a sheet, beside other controls in a line.
        self.style = style or action.default_style
        #: Where the button goes. ``"navbar"`` is the top bar beside the title,
        #: which is where both platforms keep the action that finishes a screen.
        #: ``"fab"`` floats it over the bottom-right corner as a labelled pill --
        #: the one action a screen exists to perform, kept in reach of a thumb.
        #: ``"after"`` pins it to the end of the Row it sits in.
        if place not in (None, "navbar", "navbar-left", "fab", "after"):
            raise DslError(
                f"Button(place={place!r}) is not valid; "
                "use 'navbar', 'navbar-left', 'fab' or 'after'."
            )
        self.place = place

    def bind(self, model, origin):
        self._bind_visible(model, origin)
        self.enabled = _bind_condition(self.enabled, model, origin)
        return self


    def ir(self, ctx=None):
        return {
            "type": "button",
            "id": self._nid,
            "label": self.label,
            "visible": _condition_ir(self.visible),
            # An action's default glyph is what an icon-only button shows. A
            # button that already says what it does in words does not need the
            # same thing said again in a picture beside them.
            "icon": self.icon or (None if self.label else self.action.default_icon),
            "style": self.style,
            "place": self.place,
            "enabled": _condition_ir(self.enabled),
            "action": self.action.ir(ctx),
        }


class FilterNode(Node):
    node_type = "filter"

    def __init__(self, label, domain=None, default=False):
        self.label = label
        self.domain = domain
        self.default = bool(default)

    def bind(self, model, origin):
        self.domain = bind_node(self.domain, model, origin)
        return self

    def ir(self, ctx=None):
        data = {"type": "filter", "id": self._nid, "label": self.label,
                "default": self.default}
        if _declares(ctx):
            data["domain"] = to_json(self.domain)
        return data


class SortNode(Node):
    """A named ordering made of one or more ordered terms."""

    node_type = "sort"

    def __init__(self, label, *orders, default=False, section=False):
        if not orders:
            raise DslError(f"Sort({label!r}) needs at least one field.")
        self.label = label
        self.orders = [o if isinstance(o, Order) else Order(o, "asc") for o in orders]
        self.default = bool(default)
        #: Head the rows with this sort's own name while it is in force. An
        #: ordering the reader cannot see in the rows themselves -- "recently
        #: starred", where nothing on a row shows when it was starred -- says so
        #: above them instead of leaving the order looking arbitrary.
        self.section = bool(section)

    def bind(self, model, origin):
        self.orders = [bind_node(o, model, origin) for o in self.orders]
        return self

    def is_reorderable(self, handle_field):
        """Manual drag only makes sense when the sort *is* the handle field asc."""
        if handle_field is None or len(self.orders) != 1:
            return False
        o = self.orders[0]
        return o.direction == "asc" and getattr(o.ref, "name", None) == handle_field.name

    def ir(self, ctx=None, handle_field=None):
        data = {
            "type": "sort",
            "id": self._nid,
            "label": self.label,
            "default": self.default,
            "section": self.section,
            "reorderable": self.is_reorderable(handle_field),
        }
        if _declares(ctx):
            # Переключатель без порядка -- кнопка, которая ничего не значит.
            data["orders"] = to_json(self.orders)
        return data


class SearchNode(Node):
    """Free-text fields plus the available filters and sorts."""

    node_type = "search"

    def __init__(self, *args, icon=None):
        #: The glyph of the header control that opens the sort sheet. Two
        #: arrows is what sorting looks like on both platforms -- a default.
        self.icon = icon or "swap_vert"
        self.fields = []
        self.filters = []
        self.sorts = []
        for a in args:
            if isinstance(a, FilterNode):
                self.filters.append(a)
            elif isinstance(a, SortNode):
                self.sorts.append(a)
            elif isinstance(a, (Ref, Field)):
                self.fields.append(a)
            else:
                raise DslError(
                    "Search(...) accepts field references, Filter(...) and Sort(...); "
                    f"got {type(a).__name__}."
                )

    def bind(self, model, origin):
        self.fields = [_bind_ref(f, model, origin) for f in self.fields]
        for f in self.filters:
            f.bind(model, origin)
        for s in self.sorts:
            s.bind(model, origin)
        return self

    def default_filter_index(self):
        for i, f in enumerate(self.filters):
            if f.default:
                return i
        return None

    def default_sort_index(self):
        for i, s in enumerate(self.sorts):
            if s.default:
                return i
        return 0 if self.sorts else None

    def ir(self, ctx=None, handle_field=None):
        return {
            "type": "search",
            "icon": self.icon,
            "fields": [f.name for f in self.fields],
            "placeholder": ", ".join(f.display_label for f in self.fields),
            "filters": [f.ir(ctx) for f in self.filters],
            "sorts": [s.ir(ctx, handle_field) for s in self.sorts],
            "default_filter": self.default_filter_index(),
            "default_sort": self.default_sort_index(),
        }


def _empty_lines(empty):
    """What ``List(empty=...)`` was given, as the lines to draw.

    One string is the whole of it -- the common case, and it should cost one
    word. A pair is a line and the line under it, which is what iOS calls
    ``text``/``secondaryText`` and Material describes as a title with supporting
    text. Neither platform offers more than two, so neither does this.

    Only the list knows what its rows are, so only the list says what their
    absence means; there is no framework wording standing in for it.
    """
    if empty is None:
        return None
    if isinstance(empty, str):
        return [empty]
    if (isinstance(empty, (tuple, list)) and 1 <= len(empty) <= 2
            and all(isinstance(line, str) for line in empty)):
        return list(empty)
    raise DslError(
        "List(empty=...) takes the line an empty list shows, or two of them -- "
        f"a line and the line under it; got {empty!r}."
    )


class ListNode(Node):
    """Query many records of *model* and render each with the *item* view."""

    node_type = "list"

    #: How a list presents itself.
    #:   "auto"     -- rows, and an opened record beside them on a wide window
    #:   "list"     -- rows, always
    #:   "table"    -- a table wherever the columns fit, rows where they do not
    #:   "timeline" -- Framework7's Timeline, one entry per record
    DISPLAYS = ("auto", "list", "table", "timeline")

    def __init__(self, model, item=None, open=None, domain=None, search=None,
                 order=None, page_size=60, display="auto", columns=None,
                 index=False, label=None, menu=None, empty=None, row_height=52):
        if display not in self.DISPLAYS:
            raise DslError(
                f"List(display={display!r}) is not valid."
                + did_you_mean(display, self.DISPLAYS)
                + f" Valid values: {', '.join(self.DISPLAYS)}."
            )
        self.display = display
        #: Heading of the list, sharing its line with the filters, the sort and
        #: the menu. A plain string, a ``"{item.name}"`` template, or a
        #: reference to view state -- the header then names whatever record that
        #: state points at.
        self.label = parse_template(label)
        #: Actions about the list itself, behind the header's three dots.
        self.menu = menu
        #: Framework7's List Index: an alphabetical scrubber down the side.
        #: Only meaningful for rows, and only worth it for a long list.
        self.index = bool(index)
        #: explicit table columns; without them the item view's cells are used,
        #: which is right until a phone row wants fewer things than a table
        self.column_nodes = [_as_node(c) for c in (columns or ())]
        self.model = model
        self.item_view = item
        self.open_view = open
        self.domain = domain
        self.search = search
        # Скребок берёт буквы из заголовков разделов, а заголовки ставит
        # сортировка -- `Sort(..., section=True)`. Без единой такой сортировки
        # индексировать ему нечего, и полоска выходит пустой: она есть, за неё
        # тянут, и ничего не происходит. Молчать об этом нельзя -- увидеть
        # такое можно только глазами и только на длинном списке.
        #
        # Поймано на живом: в примере kitchen `index=True` стоял без разделов,
        # и единственным «заголовком», который скребок находил, была наша шапка
        # отборов -- она лежала в том же `ul` и несла тот же класс. Когда шапка
        # переехала над карточкой, скребок опустел.
        if self.index and not any(s.section for s in (search.sorts if search else ())):
            raise DslError(
                f"List({model.__name__}, index=True), но ни одна Sort не "
                "объявила section=True. Скребку нечего индексировать: буквы он "
                "берёт из заголовков разделов, а ставит их сортировка. "
                "Добавьте section=True нужной сортировке или уберите index=True."
            )
        self.order = list(order) if isinstance(order, (list, tuple)) else (
            [order] if order is not None else None
        )
        #: rows fetched per page; the renderer asks for more as the user scrolls
        self.page_size = page_size
        #: What an empty list says. The framework has a wording for it, but only
        #: the app knows what these rows are, so it can say so itself.
        self.empty = _empty_lines(empty)
        #: What one row is expected to measure. Only virtualisation reads it --
        #: it decides how many rows to keep in the document -- and a list whose
        #: rows wrap runs taller than the default.
        self.row_height = row_height
        #: The item view's tree for this render. A `ui` method describes the
        #: row in terms of the data, so there is no one tree to point at until
        #: the screen draws: the runtime builds it and hands it over here.
        self.item_root = None
        self._validated = False

    def _origin(self):
        return f"List({getattr(self.model, '__name__', self.model)})"

    def validate(self):
        """Bind refs and check that the item/open views match the list model."""
        if self._validated:
            return
        from .view import View

        model = self.model
        if not hasattr(model, "_fields"):
            raise DslError(
                f"List(...) expects a Model class, got {model!r}."
            )
        origin = self._origin()
        self.domain = bind_node(self.domain, model, origin)
        # `order=` names fields of the same model, so it binds with the domain;
        # without this the reference reaches the query still unbound.
        if self.order:
            self.order = [bind_node(o, model, origin) for o in self.order]
        if self.search is not None:
            if not isinstance(self.search, SearchNode):
                raise DslError("List(search=...) expects Search(...).")
            self.search.bind(model, origin)

        for node in self.column_nodes:
            node.bind(model, origin)

        for kind, v in (("item", self.item_view), ("open", self.open_view)):
            if v is None:
                continue
            if not (isinstance(v, type) and issubclass(v, View)):
                raise DslError(
                    f"List({model.__name__}, {kind}=...) expects a View class, got {v!r}."
                )
            if v._model is not model:
                bound = getattr(v._model, "__name__", None)
                raise DslError(
                    f"{v.__name__} is bound to {bound} but "
                    f"List expects {model.__name__}."
                )
        self._validated = True

    def walk(self):
        # The menu hangs off the list rather than standing in the tree, and
        # every walk has to reach it: ids are assigned by one, and the index
        # that dispatches a button by id is built by another.
        yield self
        if self.menu is not None:
            yield from self.menu.walk()

    def _swipe_button(self):
        """The Delete button in the item view that asked for a swipe, if any."""
        if self.item_root is None:
            return None
        for node in self.item_root.walk():
            if isinstance(node, ButtonNode) and getattr(node.action, "swipe", False):
                return node
        return None

    def swipe_delete(self):
        """Id of a Delete button in the item view that asked for swipe."""
        button = self._swipe_button()
        return button._nid if button is not None else None

    def _swipe_label(self):
        """What the revealed action is called -- the button's own word for it."""
        button = self._swipe_button()
        return button.label if button is not None else None

    def columns(self):
        """Header cells for the table presentation.

        By default the columns *are* the item view: whatever a row shows side by
        side is what a table shows in columns, so an app never describes its
        list twice. ``columns=(...)`` overrides that, for the case where a phone
        row should stay shorter than the table.
        """
        children = self.column_nodes
        if not children:
            if self.item_root is None:
                return []
            children = self.item_root.children
            if len(children) == 1 and isinstance(children[0], RowNode):
                children = children[0].children
        out = []
        for node in children:
            label, numeric = "", False
            if isinstance(node, FieldNode):
                field = node.field
                widget = node.widget or getattr(field, "default_widget", None)
                if node.widget == "handle":
                    label = ""
                elif node.label is not None:
                    label = node.label
                elif isinstance(field, Field):
                    label = field.display_label
                numeric = (
                    getattr(field, "ftype", None) in _NUMERIC_TYPES
                    and widget in _NUMERIC_WIDGETS
                )
            out.append({"id": node._nid, "label": label, "numeric": numeric})
        return out

    def handle_node(self):
        """The field node the item view draws as a drag handle, if any."""
        if self.item_root is None:
            return None
        for node in self.item_root.walk():
            if isinstance(node, FieldNode) and node.widget == "handle":
                return node
        return None

    def handle_field(self):
        """The Integer field rendered as a drag handle by the item view, if any."""
        node = self.handle_node()
        return node.field if node else None

    def ir(self, ctx=None):
        self.validate()
        handle_node = self.handle_node()
        handle = handle_node.field if handle_node else None
        data = {
            "type": "list",
            "id": self._nid,
            "model": self.model.__name__,
            "model_label": self.model._label,
            # A reference is resolved against live view state by the runtime,
            # which is the only place that can read it; a template is resolved
            # when the document is expanded.
            "label": _text_ir(self.label) if not isinstance(self.label, Ref) else None,
            "menu": self.menu.ir(ctx) if self.menu is not None else None,
            "item": self.item_view.__name__ if self.item_view else None,
            "open": self.open_view.__name__ if self.open_view else None,
            "swipe_label": self._swipe_label(),
            "row_height": self.row_height,
            "empty": self.empty,
            "display": self.display,
            "index": self.index,
            "columns": self.columns(),
            "own_columns": bool(self.column_nodes),
            "page_size": int(self.page_size),
            "handle_field": handle.name if handle else None,
            "handle_hidden": handle_node.visible is False if handle_node else False,
            "swipe_delete": self.swipe_delete(),
            "search": self.search.ir(ctx, handle) if self.search else None,
        }
        if _declares(ctx):
            # Какие записи показывать -- вопрос, а не ответ, и в документе он
            # обязан сохраниться: без него список описывает форму строки и
            # молчит о том, что в ней стоит.
            data["domain"] = to_json(self.domain)
            data["order"] = to_json(list(self.order or []))
            # Заголовки таблицы (``columns``) описывают шапку, а нарисовать
            # ячейку по ним нельзя: в ней стоит узел, а не подпись. Без этого
            # ``columns=(...)`` доезжает до устройства половиной -- шапка
            # объявленная, а строки нарисованы видом строки, то есть чужие.
            # Ловится только на приложении с таблицей: в gtasks её нет.
            data["column_nodes"] = [c.ir(ctx) for c in self.column_nodes] or None
        return data


# --------------------------------------------------------------------------
# actions
# --------------------------------------------------------------------------
#: Where an action puts the screen it opens.
#:   "page"  -- pushed onto the stack, with a bar and a back gesture
#:   "sheet" -- risen over what is already there, dismissed by dragging it down
#:
#: Odoo's word, and for Odoo's reason: ``target`` sits on ``ir.actions.act_window``
#: and not on the form, so the same form is `current` from a list and `new` as a
#: quick create. UIKit says it by having two calls at the call site
#: (``pushViewController`` against ``present(_:animated:)``), SwiftUI by hanging
#: ``.sheet(isPresented:)`` where the screen is opened. Ours are these two words
#: rather than Odoo's `current`/`new`, which name slots in a desktop window that a
#: phone does not have -- while "page" and "sheet" are the two surfaces both
#: platforms actually draw, and the words the rest of this DSL already uses
#: (``Group(surface="sheet")``, Framework7's `.page` and Sheet Modal). Odoo's
#: third value, `fullscreen`, is left out: nothing here would behave differently.
TARGETS = ("page", "sheet")


def _check_target(value, where):
    if value not in TARGETS:
        raise DslError(
            f"{where}(target={value!r}) is not valid."
            + did_you_mean(value, TARGETS)
            + f" Valid values: {', '.join(TARGETS)}."
        )
    return value


class Action:
    """Behaviour attached to a :class:`ButtonNode`."""

    action_type = "action"
    default_icon = None
    default_style = "default"
    #: does running this action close the current detail screen?
    closes_screen = False

    def ir(self, ctx=None):
        return {"type": self.action_type}


class DeleteAction(Action):
    action_type = "delete"
    default_icon = "delete"
    default_style = "destructive"
    closes_screen = True

    def __init__(self, model=None, record_id=None, confirm=True, swipe=False,
                 domain=None):
        #: Named outright when the button is not inside the record it deletes --
        #: a list menu removing its own list, for one.
        self.model = model
        self.record_id = record_id
        #: Which records to remove, as a question rather than as an answer.
        #: A list of ids is worked out when the screen is drawn and pressed
        #: минутой позже -- удалится то, что было, а не то, что человек видит.
        #: A domain is answered at the moment of the tap, which is the only
        #: moment that matters.
        self.domain = domain
        self.confirm = parse_template(confirm)
        #: also expose this delete as a swipe-to-delete gesture on the row
        self.swipe = swipe

    def ir(self, ctx=None):
        if _declares(ctx):
            return {
                "type": "delete",
                "confirm": (
                    bool(self.confirm) if isinstance(self.confirm, bool)
                    else _text_ir(self.confirm)
                ),
                "swipe": bool(self.swipe),
                # Кого удалять. Без этих трёх `Delete(Board, item.id)`,
                # `Delete(Task, domain=...)` и голый `Delete()` в документе
                # неразличимы, а делают они совершенно разное.
                "model": _named(self.model),
                "record_id": to_json(self.record_id),
                "domain": to_json(self.domain),
            }
        return {
            "type": "delete",
            # A string is the question to ask; True is "ask, in the framework's
            # own words"; False asks nothing. A template is a question that
            # names the record, and it is a string by the time it is asked.
            "confirm": (
                bool(self.confirm) if isinstance(self.confirm, bool)
                else _text_ir(self.confirm)
            ),
            "swipe": bool(self.swipe),
        }


class SetAction(Action):
    """Write a value -- ``Set(done, True)``, ``Set(view.details, True)``.

    The missing half of the vocabulary: every other action navigates or removes,
    and a screen whose whole purpose is one change -- Google's "Выполнено", a
    row of icons that reveal the fields behind them -- had nothing to say.

    A record field is written to the record the button sits in; ``view.<name>``
    is screen state and never reaches the database.
    """

    action_type = "set"
    default_icon = "check"

    def __init__(self, ref, value=True):
        name = getattr(ref, "name", None) or getattr(ref, "ref_name", None)
        if not name:
            raise DslError(
                f"Set(...) needs a field, e.g. Set(done, True); got {ref!r}."
            )
        self.name = name
        self.scope = "view" if type(ref).__name__ == "ViewFieldRef" else "record"
        self.value = value

    def ir(self, ctx=None):
        return {"type": "set", "field": self.name, "scope": self.scope,
                "value": self.value}


class OpenAction(Action):
    """Open one record in a view -- ``Open(BoardCard, board.id)``.

    A `ui` method knows the record it is drawing for, so the action names it
    outright instead of pointing at a field and hoping.

    ``target`` says how that screen arrives -- see :data:`TARGETS`.
    """

    action_type = "open"
    default_icon = "edit"

    def __init__(self, view, record_id, target="page"):
        self.view = view
        self.record_id = record_id
        self.target = _check_target(target, "Open")

    def ir(self, ctx=None):
        if _declares(ctx):
            return {
                "type": "open",
                "view": _named(self.view),
                "record_id": to_json(self.record_id),
                "target": self.target,
            }
        return {"type": "open"}


class SaveAction(Action):
    """Insert the draft this screen is editing, then leave.

    Only a screen opened by ``Create`` has one; anywhere else the button just
    goes back, because an existing record is already saved with every keystroke.
    """

    action_type = "save"
    default_icon = "check"
    closes_screen = True

    def ir(self, ctx=None):
        return {"type": "save"}


class CreateAction(Action):
    """Make a record and open it -- ``Create(Board, open=BoardCard)``.

    What a "+ new" affordance does anywhere: the row exists first, then the
    screen that lets it be named. ``draft=True`` holds it back instead --
    nothing is written until a ``Save()``, which is what a form with a "done"
    button means and what both platforms do in a quick-create sheet.

    ``values`` is what the new record starts as. A literal, or ``view.<name>``
    for a piece of screen state -- the tag a list is filtered by, the board a
    tab is showing. Said outright, because the record has to belong where the
    user made it and nothing else on the screen can be asked about that.

    ``target`` says how the screen arrives -- see :data:`TARGETS`. A quick
    create is the case both platforms give a sheet: one record added without
    leaving the list it belongs to.
    """

    action_type = "create"
    default_icon = "add"

    def __init__(self, model, open=None, values=None, draft=False, target="page"):
        self.model = model
        self.view = open
        self.values = dict(values or {})
        self.draft = bool(draft)
        self.target = _check_target(target, "Create")

    def ir(self, ctx=None):
        if _declares(ctx):
            return {
                "type": "create",
                "model": _named(self.model),
                "view": _named(self.view),
                # Чем запись начинается: литерал или `view.<имя>` -- то и другое
                # едет выражением, потому что второе отвечается на устройстве.
                "values": {k: to_json(v) for k, v in self.values.items()},
                "draft": self.draft,
                "target": self.target,
            }
        return {"type": "create"}


class LogicAction(Action):
    """Позвать объявленное действие -- ``Logic("Task.complete")``.

    Шестое действие рядом с пятью, которые фреймворк исполняет сам. Разница
    ровно одна и она вся здесь: пять первых знают, *что* делают, а это знает
    только **имя**. Что за ним стоит -- модуль на Rust, модуль на C или
    питоновская функция -- отсюда не видно и видно быть не должно: иначе кнопка
    в документе вида начала бы зависеть от языка, на котором написана логика, и
    документ перестал бы быть переносимым.

    Ключи записи кнопка не повторяет: экран их знает, а куда их положить, знает
    объявление -- см. ``oneframework.wasm.store.bind_args``.
    """

    action_type = "logic"
    default_icon = "play_arrow"

    def __init__(self, name, args=None, closes_screen=False):
        # Ссылкой на метод модели, а не строкой: `Logic(Note.summary)`.
        # Строка тоже принимается -- логика бывает объявлена не методом, а
        # правилом или чужим модулем, -- но там, где метод есть, ссылка на
        # него лучше во всём: её проверяет редактор, по ней работает переход к
        # определению и переименование, и опечатка в ней не доживает до
        # устройства.
        if hasattr(name, "declaration") and hasattr(name, "writes"):
            name = name.name
        if not isinstance(name, str):
            raise DslError(
                f"Logic(...) ждёт метод модели или его имя, получено {name!r}.\n"
                "    Logic(Note.summary)"
            )
        self.name = name
        self.args = dict(args or {})
        self.closes_screen = bool(closes_screen)

    def ir(self, ctx=None):
        if _declares(ctx):
            return {
                "type": "logic",
                "name": self.name,
                "args": {k: to_json(v) for k, v in self.args.items()},
                "closes_screen": self.closes_screen,
            }
        # На проводе от действия остаётся только тип: нажатие возвращается сюда
        # номером кнопки, и что за ним стоит, решает рантайм, а не рендерер.
        return {"type": "logic"}


def _as_node(obj):
    if isinstance(obj, Node):
        return obj
    if isinstance(obj, Ref):
        # `record.text` used where `record.text()` was meant -- be forgiving,
        # render the field's default widget.
        return FieldNode(obj)
    raise DslError(
        f"{obj!r} is not a UI component. Use a field call like record.text(), "
        "Row(...), List(...) or Button(...)."
    )


_PREFIX = {
    "view": "v", "row": "r", "col": "c", "group": "g", "section": "sec",
    "repeat": "rep",
    "tabs": "tb", "tab": "tab", "field": "f", "list": "l", "accordion": "acc",
    "button": "b", "search": "s", "filter": "flt", "sort": "srt", "menu": "m",
    "pill": "p", "text": "txt", "icon": "ic",
}


def assign_ids(root, view_name):
    """Give every node in *root* a stable id, unique within its View."""
    counters: dict[str, int] = {}

    def visit(node):
        prefix = _PREFIX.get(node.node_type, "n")
        counters[prefix] = counters.get(prefix, 0) + 1
        node._nid = f"{view_name}.{prefix}{counters[prefix]}"
        if isinstance(node, ListNode):
            for column in node.column_nodes:
                visit(column)
            if node.search is not None:
                visit(node.search)
                for child in node.search.filters + node.search.sorts:
                    visit(child)

    for node in root.walk():
        visit(node)
    return root


#: ``is_visible`` и ``is_enabled`` жили здесь: они вычисляли условие узла на
#: записи питоновским вычислителем. Решает это устройство
#: (`libs/js/src/core/runtime/expand.js` через `libs/js/src/core/expr.js`), и питоновский был вторым.
#:
#: Перед удалением оба сверены. Разошлись ровно в одном: **пропущенный ключ
#: записи**. У устройства он значит «не выбрано» и расширяет условие, у питона
#: значил «нет значения». Случай недостижим -- колонка приходит из базы всегда,
#: пустая приезжает как `null`, и на `null` стороны отвечали одинаково.
