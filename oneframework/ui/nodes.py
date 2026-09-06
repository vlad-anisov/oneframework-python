"""Component IR."""

from __future__ import annotations

from ..errors import DslError, did_you_mean
from ..model.expr import (
    Expr, ItemFieldRef, Order, RecordFieldRef, Ref,
    iter_refs, map_refs, parse_template,
)
# Imported here rather than inside the methods that use it: the browser host
# snapshots the interpreter once everything is imported and then throws the
# filesystem away, so a module first imported while the app is drawing exists
# on the cold start and is gone on every warm one.
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

_NUMERIC_TYPES = frozenset(
    {"integer", "float", "monetary", "percent", "duration", "rating"}
)
#: ...but only when the cell is the number itself.
_NUMERIC_WIDGETS = frozenset({"number", "monetary", "percent", "duration"})

class Node:
    node_type = "node"
    _nid = None
    #: When this node is drawn: ``True``/``False`` outright, or a domain
    #: expression over ``record.<field>`` answered per record.
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

DOCUMENT = "document"

def _declares(ctx):
    return ctx == DOCUMENT

def _named(value):
    """Класс модели или вида едет в документ именем, а не объектом."""
    return getattr(value, "__name__", value) if value is not None else None

def _text_ir(value):
    if value is None or isinstance(value, str):
        return value
    return to_json(value)

def _condition_ir(value):
    """``visible=`` / ``enabled=`` так, как они едут в документе."""
    if isinstance(value, bool):
        return value
    return to_json(value)

def _bind_ref(ref, model, origin):
    """Turn ``record.<name>`` into the real :class:`Field` of *model*."""
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
    """``visible=`` / ``enabled=``: a plain answer, or a condition to resolve."""
    if isinstance(value, bool):
        return value
    return bind_node(value, model, origin)

def bind_node(node, model, origin):
    if isinstance(node, Node):
        return node.bind(model, origin)
    if node is None:
        return None
    return map_refs(node, lambda r: _bind_ref(r, model, origin))

# --- structural nodes --------------------------------------------------------
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
            # читающий `self`.
            data["title"] = None if callable(title) else title
            data["title_is_code"] = callable(title)
            data["dismiss"] = getattr(self.view_cls, "_dismiss", "auto")
            data["crumbs"] = getattr(self.view_cls, "_crumbs", None)
            # Состояние экрана -- поля, которые никогда не станут колонкой.
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
        """``item.`` resolves against *our* model, ``record.`` against the outer one."""
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
    node_type = "menu"

    def __init__(self, *children, place=None, icon=None):
        self.children = [_as_node(c) for c in children]
        if place not in (None, "navbar", "navbar-left"):
            raise DslError(
                f"Menu(place={place!r}) is not valid; use 'navbar' or 'navbar-left'."
            )
        self.place = place
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
    node_type = "col"

    def __init__(self, *children, span=None):
        self.children = [_as_node(c) for c in children]
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

GROUP_SURFACES = ("card", "sheet")

class GroupNode(Node):
    """Odoo's ``<group>``: a titled block of fields."""
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
    """A titled block that collapses -- Framework7's Accordion."""
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
    """A count beside a label -- ``Tab("Работа", Pill(3))``."""
    node_type = "pill"

    WHENS = ("always", "closed")

    def __init__(self, value, when="always"):
        if when not in self.WHENS:
            raise DslError(
                f"Pill(when={when!r}) is not valid."
                + did_you_mean(when, self.WHENS)
                + f" Valid values: {', '.join(self.WHENS)}."
            )
        #: A number, or the question that answers to one -- ``Count(Task,
        #: ...)``.
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
    """A glyph where a piece of text would go -- ``Tab(Icon("star"), ...)``."""
    node_type = "icon"

    def __init__(self, name):
        self.name = str(name)

    def ir(self, ctx=None):
        return {"type": "icon", "id": self._nid, "name": self.name}

    def bind(self, model, origin):
        return self

class TabNode(Node):
    """One page of a :class:`TabsNode` -- Odoo's ``<page>``."""
    node_type = "tab"

    TITLE_PARTS = (TextNode, IconNode, PillNode)

    def __init__(self, label, *children):
        title = [TextNode(label)] if isinstance(label, str) else [_as_node(label)]
        content = []
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
        yield from self.title
        if self.fab is not None:
            yield from self.fab.walk()
        for c in self.children:
            yield from c.walk()

class TabsNode(Node):
    """Odoo's ``<notebook>``: several pages, one visible at a time."""
    node_type = "tabs"

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
    node_type = "field"

    def __init__(self, field, widget=None, label=None, visible=True, place=None,
                 placeholder=None, **options):
        self.field = field
        self.widget = widget
        self.label = label
        self.placeholder = placeholder
        #: ``visible=False`` is declared but never drawn: the field still
        #: counts for everything the DSL reads off the tree -- an undrawn
        #: ``widget="handle"`` still makes its list reorderable -- it simply
        #: takes no room.
        self.visible = visible
        #: ``place="navbar"`` puts the control in the top bar rather than in
        #: the body.
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
        # Метод модели -- сам себе действие: `action=Note.summary`.
        if hasattr(action, "declaration") and hasattr(action, "writes"):
            action = LogicAction(action)
        if not isinstance(action, Action):
            raise DslError(
                f"Button action must be an Action instance, got {type(action).__name__}."
            )
        self.label = label
        self.icon = icon
        self.action = action
        #: Drawn outright, never, or per record -- see :attr:`Node.visible`.
        self.visible = visible
        self.enabled = enabled if isinstance(enabled, (Expr, Ref)) else bool(enabled)
        #: ``"plain"`` is a labelled action with no fill -- a word you press.
        self.style = style or action.default_style
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
            # An action's default glyph is what an icon-only button shows.
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
    node_type = "sort"

    def __init__(self, label, *orders, default=False, section=False):
        if not orders:
            raise DslError(f"Sort({label!r}) needs at least one field.")
        self.label = label
        self.orders = [o if isinstance(o, Order) else Order(o, "asc") for o in orders]
        self.default = bool(default)
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
    node_type = "search"

    def __init__(self, *args, icon=None):
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
    """What ``List(empty=...)`` was given, as the lines to draw."""
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
    node_type = "list"

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
        #: the menu.
        self.label = parse_template(label)
        self.menu = menu
        #: Framework7's List Index: an alphabetical scrubber down the side.
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
        # сортировка -- `Sort(..., section=True)`.
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
        #: rows fetched per page; the renderer asks for more as the user
        #: scrolls
        self.page_size = page_size
        self.empty = _empty_lines(empty)
        self.row_height = row_height
        self.item_root = None
        self._validated = False

    def _origin(self):
        return f"List({getattr(self.model, '__name__', self.model)})"

    def validate(self):
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
        if self.item_root is None:
            return None
        for node in self.item_root.walk():
            if isinstance(node, ButtonNode) and getattr(node.action, "swipe", False):
                return node
        return None

    def swipe_delete(self):
        button = self._swipe_button()
        return button._nid if button is not None else None

    def _swipe_label(self):
        button = self._swipe_button()
        return button.label if button is not None else None

    def columns(self):
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
            # ячейку по ним нельзя: в ней стоит узел, а не подпись.
            data["column_nodes"] = [c.ir(ctx) for c in self.column_nodes] or None
        return data

# --------------------------------------------------------------------------
# actions
# --------------------------------------------------------------------------
# Where an action puts the screen it opens.
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
        #: Named outright when the button is not inside the record it deletes
        #: -- a list menu removing its own list, for one.
        self.model = model
        self.record_id = record_id
        self.domain = domain
        self.confirm = parse_template(confirm)
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
                "model": _named(self.model),
                "record_id": to_json(self.record_id),
                "domain": to_json(self.domain),
            }
        return {
            "type": "delete",
            # A string is the question to ask; True is "ask, in the framework's
            # own words"; False asks nothing.
            "confirm": (
                bool(self.confirm) if isinstance(self.confirm, bool)
                else _text_ir(self.confirm)
            ),
            "swipe": bool(self.swipe),
        }

class SetAction(Action):
    """Write a value -- ``Set(done, True)``, ``Set(view.details, True)``."""
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
    """Open one record in a view -- ``Open(BoardCard, board.id)``."""
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
    action_type = "save"
    default_icon = "check"
    closes_screen = True

    def ir(self, ctx=None):
        return {"type": "save"}

class CreateAction(Action):
    """Make a record and open it -- ``Create(Board, open=BoardCard)``."""
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
                # Чем запись начинается: литерал или `view.<имя>` -- то и
                # другое едет выражением, потому что второе отвечается на
                # устройстве.
                "values": {k: to_json(v) for k, v in self.values.items()},
                "draft": self.draft,
                "target": self.target,
            }
        return {"type": "create"}

class LogicAction(Action):
    """Позвать объявленное действие -- ``Logic("Task.complete")``."""
    action_type = "logic"
    default_icon = "play_arrow"

    def __init__(self, name, args=None, closes_screen=False):
        # Ссылкой на метод модели, а не строкой: `Logic(Note.summary)`.
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
#: записи питоновским вычислителем.
