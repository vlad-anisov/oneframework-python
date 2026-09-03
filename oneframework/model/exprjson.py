"""Дерево выражения ⇄ JSON.

Узлов здесь мало, и это главное про этот файл. Выражение пишется **строкой**
(:func:`~oneframework.model.expr.expr`), а дерево из неё собирает сборка --
один разборщик на все языки (``libs/js/src/build/exprtext.mjs``). Привязке
остаётся напечатать то немногое, что она строит сама: ссылку на поле, шаблон,
порядок и саму строку.

Форма выбрана короткой, потому что дерево едет по сети внутри каждого
документа вида::

    {"op": "&", "p": [{"r": "starred"}, {"op": "!", "e": {"r": "done"}}]}

Перечня узлов здесь нет намеренно: он один на все языки и лежит в
``protocol/expression.json``. Пересказ был бы вторым описанием, и разошлись бы
они молча: чужая библиотека читает не докстроку, а файл.
"""

from __future__ import annotations

from ..errors import DslError
from .expr import (
    UNSET, ItemFieldRef, Order, RecordFieldRef, Ref, Template, TextExpr,
    ViewFieldRef,
)

__all__ = ["to_json", "from_json"]

#: Литералы, которые JSON несёт сам и переводить не нужно.
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
        # Поле модели, названное само собой: `enabled=Note.title`. Область у
        # такого -- запись, потому что другой у поля модели и не бывает.
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
    """JSON -> узел. Обратная дорога: ею читают уже выложенный документ.

    Узлы, которых привязка не строит (сравнения, арифметика, свёртки), из
    JSON тоже не собираются: собрать их значило бы завести второй способ
    получить дерево -- тот самый, от которого и уходили. Такое возвращается
    как есть, словарём: читателю этого хватает, а построить из него выражение
    он не сможет и не должен.
    """
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
