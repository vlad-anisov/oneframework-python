"""Дерево выражения ⇄ JSON."""

from __future__ import annotations

from ..errors import DslError
from .expr import (
    UNSET, ItemFieldRef, Order, RecordFieldRef, Ref, Template, TextExpr,
    ViewFieldRef,
)

__all__ = ["to_json", "from_json"]

_SCALARS = (str, int, float, bool, type(None))

def to_json(node):
    """Узел -> JSON. Отказ вслух: молча напечатанное не то доедет до устройства."""
    if node is UNSET:
        return {"unset": True}
    if isinstance(node, _SCALARS):
        return node
    if isinstance(node, TextExpr):
        return {"text": node.text}
    if isinstance(node, RecordFieldRef):
        return {"r": node.name}
    if isinstance(node, ViewFieldRef):
        return {"v": node.name}
    if isinstance(node, ItemFieldRef):
        return {"i": node.name}
    if isinstance(node, Ref):
        # Поле модели, названное само собой: `enabled=Note.title`.
        имя = getattr(node, "name", None)
        if имя is None:
            raise DslError(f"Ссылку {node!r} нельзя записать в документ: нет имени.")
        return {"r": имя}
    if isinstance(node, (list, tuple)):
        return [to_json(э) for э in node]
    if isinstance(node, Template):
        return {"fmt": [to_json(ч) for ч in node.parts]}
    if isinstance(node, Order):
        return {"order": to_json(node.ref), "dir": node.direction}
    raise DslError(
        f"{type(node).__name__} не печатается в JSON. Выражение записывается "
        'строкой: expr("record.done & !record.archived") -- одна запись на все '
        "три языка, и разбирает её сборка.")

def from_json(data):
    if isinstance(data, _SCALARS):
        return data
    if not isinstance(data, dict):
        raise DslError(f"узел выражения -- это объект, а не {type(data).__name__}")
    if data.get("unset") is True:
        return UNSET
    if set(data) == {"text"}:
        return TextExpr(data["text"])
    for ключ, класс in (("r", RecordFieldRef), ("v", ViewFieldRef), ("i", ItemFieldRef)):
        if set(data) == {ключ}:
            return класс(data[ключ])
    if set(data) == {"fmt"}:
        return Template([from_json(ч) for ч in data["fmt"]])
    if set(data) == {"order", "dir"}:
        return Order(from_json(data["order"]), data["dir"])
    return data
