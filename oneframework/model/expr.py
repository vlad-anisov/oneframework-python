"""Expression AST, context proxies and the UNSET sentinel."""

from __future__ import annotations

import re

import ast
import inspect
import textwrap

from ..errors import DslError, did_you_mean

__all__ = [
    "Expr",
    "ItemFieldRef",
    "Order",
    "RecordFieldRef",
    "Ref",
    "Template",
    "UNSET",
    "ViewFieldRef",
    "item",
    "iter_refs",
    "map_refs",
    "parse_template",
    "record",
    "view",
]

class _Unset:
    _instance = None

    def __repr__(self):
        return "UNSET"

    def __bool__(self):
        return False

UNSET = _Unset()

class Expr:
    def __bool__(self):
        raise DslError(
            f"{type(self).__name__} cannot be used as a Python boolean. "
            "Combine domain expressions with '&', '|' and '~' "
            "(e.g. (flag == False) & (rank > 0))."
        )

    def _map_refs(self, fn):  # pragma: no cover - overridden
        raise NotImplementedError

class Ref:
    __hash__ = object.__hash__

    def is_null(self):
        """Explicit SQL ``NULL`` test (never implied by UNSET)."""
    def asc(self):
        return Order(self, "asc")

    def desc(self):
        return Order(self, "desc")

    @property
    def ref_name(self):  # pragma: no cover - overridden
        raise NotImplementedError

class _NamedRef(Ref):
    __hash__ = object.__hash__

    def __bool__(self):
        raise DslError(
            f"{self!r} -- это ссылка на поле, а не значение: «истинно ли оно» "
            "станет известно только у базы. Напишите тройное выражение "
            "(a if ... else b) -- оно уедет в запрос ветвлением."
        )

    def __init__(self, name):
        self.name = name

    @property
    def ref_name(self):
        return self.name

    def __call__(self, widget=None, label=None, **options):
        from ..ui.nodes import FieldNode

        return FieldNode(self, widget=widget, label=label, **options)

class _SliceRefused:
    """Срез у ссылки -- тот же отказ, что и у выражения."""
class RecordFieldRef(_NamedRef, _SliceRefused):
    """``record.tag`` -- a column of the row currently being evaluated."""
    __hash__ = object.__hash__
    ftype = None

    def typed(self, ftype):
        other = RecordFieldRef(self.name)
        other.ftype = ftype
        return other

    def __getattr__(self, name):
        return _string_method(self, name, f"поля «{self.name}»")

    def __repr__(self):
        return f"record.{self.name}"


class ViewFieldRef(_NamedRef):
    """``view.tag`` -- transient state of the enclosing View."""
    __hash__ = object.__hash__

    def __repr__(self):
        return f"view.{self.name}"

class ItemFieldRef(_NamedRef):
    """``item.name`` -- the record the enclosing ``Repeat`` is drawing."""
    __hash__ = object.__hash__

    def __repr__(self):
        return f"item.{self.name}"

class _RecordProxy:
    def __init__(self, model=None, origin=None):
        object.__setattr__(self, "_model", model)
        object.__setattr__(self, "_origin", origin)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        model = object.__getattribute__(self, "_model")
        if name in _RECORD_METHODS:
            if model is not None and name in model._fields:
                from ..errors import DslError

                raise DslError(
                    f"у модели {model.__name__} есть поле «{name}», и оно "
                    f"закрывает собой одноимённый метод записи. Переименуйте "
                    f"поле -- иначе `record.{name}` значит то одно, то другое."
                )
            return _RECORD_METHODS[name]()
        if model is None:
            return RecordFieldRef(name)
        for action in getattr(model, "_actions", ()):
            if action.entry == name:
                return _BoundAction(action)
        if name in model._fields:
            return RecordFieldRef(name)
        from ..errors import DslError, did_you_mean

        известно = list(model._fields) + [a.entry for a in getattr(model, "_actions", ())]
        origin = object.__getattribute__(self, "_origin")
        где = f"{origin}: " if origin else ""
        raise DslError(
            f"{где}record.{name}: у модели {model.__name__} нет ни поля, ни "
            f"метода с таким именем." + did_you_mean(name, известно)
        )

    def __repr__(self):
        model = object.__getattribute__(self, "_model")
        return "record" if model is None else f"record<{model.__name__}>"

def _record_delete():
    """``record.delete()`` -- убрать эту запись из базы."""
    def delete(confirm=True, swipe=False):
        from ..ui.nodes import DeleteAction

        return DeleteAction(confirm=confirm, swipe=swipe)
    return delete

def _record_save():
    """``record.save()`` -- записать черновик."""
    def save():
        from ..ui.nodes import SaveAction

        return SaveAction()
    return save

def _record_open():
    """``record.open(Card)`` -- показать эту запись названным видом."""
    def open_(view, target="page"):
        from ..ui.nodes import OpenAction

        return OpenAction(view, None, target=target)
    return open_

_RECORD_METHODS = {
    "delete": _record_delete,
    "save": _record_save,
    "open": _record_open,
}

class _BoundAction:
    """Метод модели, позванный на рисуемой записи: ``record.summary()``."""
    def __init__(self, action):
        self.action = action

    def __call__(self, **kw):
        from ..ui.nodes import LogicAction

        return LogicAction(self.action, **kw)

    def __repr__(self):
        return f"<record.{self.action.entry}>"

class _ViewProxy:
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return ViewFieldRef(name)

    def __repr__(self):
        return "view"

class _ItemProxy:
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return ItemFieldRef(name)

    def __repr__(self):
        return "item"

record = _RecordProxy()
view = _ViewProxy()
item = _ItemProxy()

class TextExpr(Expr):
    """Выражение, записанное **строкой**: ``expr("record.n * 2 > 10")``."""
    def __init__(self, text):
        if not isinstance(text, str):
            raise DslError(
                f"expr(...) ждёт строку, получено {text!r}.\n"
                '    expr("record.n * 2 > 10")')
        self.text = text

    def __repr__(self):
        return f"expr({self.text!r})"

    def _map_refs(self, fn):
        return self

def expr(text):
    return TextExpr(text)

class Template(Expr):
    """Строка со ссылками внутри -- ``"Удалить «{item.name}»?"``."""
    def __init__(self, parts):
        self.parts = list(parts)

    def _map_refs(self, fn):
        return Template([_map(p, fn) for p in self.parts])

    def __repr__(self):
        inner = "".join(
            p if isinstance(p, str) else "{" + repr(p) + "}" for p in self.parts
        )
        return f"t{inner!r}"

#: ``{item.name}``.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\}")

def parse_template(text):
    """Текст -> :class:`Template`, если в нём есть ссылки, иначе он сам."""
    if not isinstance(text, str) or "{" not in text:
        return text
    parts, last = [], 0
    for match in _PLACEHOLDER.finditer(text):
        scope, name = match.group(1), match.group(2)
        if scope != "item":
            raise DslError(
                f"В шаблоне {text!r} ссылка '{scope}.{name}': подставляется "
                "только 'item.<поле>' -- запись повторителя. Условие о записи "
                "или о состоянии экрана говорится через visible=."
            )
        if match.start() > last:
            parts.append(text[last:match.start()])
        parts.append(ItemFieldRef(name))
        last = match.end()
    if not parts:
        return text
    if last < len(text):
        parts.append(text[last:])
    return Template(parts)

class Order:
    """One ordering term. A ``Sort`` may hold several."""
    def __init__(self, ref, direction="asc"):
        self.ref = ref
        self.direction = direction

    def _map_refs(self, fn):
        return Order(_map(self.ref, fn), self.direction)

    def __repr__(self):
        return f"{self.ref!r}.{self.direction}()"

def _map(node, fn):
    if isinstance(node, (Expr, Order)):
        return node._map_refs(fn)
    if isinstance(node, Ref):
        return fn(node)
    return node

def map_refs(node, fn):
    """Return a copy of *node* with every :class:`Ref` replaced by ``fn(ref)``."""
    return _map(node, fn)

def iter_refs(node):
    """Yield every :class:`Ref` appearing in *node*."""
    found = []

    def collect(ref):
        found.append(ref)
        return ref

    _map(node, collect)
    return found
