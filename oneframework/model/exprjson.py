"""Домены как данные: дерево выражения ⇄ JSON.

Условие отбора (``record.starred & ~record.done``) уже сейчас не код, а дерево
узлов. Здесь оно превращается в JSON и обратно.

Зачем это отдельным модулем, а не методом на узлах: формат обязан быть
одинаковым в Python и в любом другом языке, который однажды станет вторым
бэкендом, и в интерпретаторе на фронтенде. Пока он живёт внутри классов, он
меняется вместе с ними незаметно; здесь он один и виден целиком.

Форма выбрана короткой, потому что дерево едет по сети внутри каждого
документа вида::

    record.starred & ~record.done
    {"op": "&", "p": [{"r": "starred"}, {"op": "!", "e": {"r": "done"}}]}

Перечня узлов здесь нет намеренно: он один на все языки и лежит в
``protocol/expression.json``, а порождается из этих же веток --
:mod:`oneframework.model.exprschema`. Пересказ здесь был бы вторым описанием,
и разошлись бы они молча: чужая библиотека читает не докстроку, а файл.
"""

from __future__ import annotations

from ..errors import DslError
from .expr import (
    UNSET, Aggregate, And, Arith, Cmp, Count, Exists, IsNull, ItemFieldRef, Max,
    Min, Not, Sum, _Lookup,
    Or, Order, RecordFieldRef, Ref, Round, Template, TextExpr, ViewFieldRef,
)

__all__ = ["to_json", "from_json"]

#: Литералы, которые JSON несёт сам и переводить не нужно.
_SCALARS = (str, int, float, bool, type(None))


def to_json(node):
    """Дерево выражения -> структура, готовая для :func:`json.dumps`."""
    if node is None or isinstance(node, bool):
        # bool раньше int: True не должен уехать единицей
        return node
    if node is UNSET:
        return {"unset": True}
    if isinstance(node, _SCALARS):
        return node

    # Раньше общей ссылки: `_Lookup` -- тоже `Ref`, и общая ветка забрала бы
    # его себе, потребовав имени, которого у подзапроса нет.
    if isinstance(node, _Lookup):
        return {"lookup": node.table, "key": to_json(node.key),
                "get": to_json(node.inner)}
    if isinstance(node, RecordFieldRef):
        return {"r": node.name}
    if isinstance(node, ViewFieldRef):
        return {"v": node.name}
    if isinstance(node, ItemFieldRef):
        return {"i": node.name}
    if isinstance(node, Ref):
        # связанное поле модели: у него уже есть имя, область -- запись
        name = getattr(node, "name", None)
        if name is None:
            raise DslError(f"Ссылку {node!r} нельзя записать в документ: нет имени.")
        return {"r": name}

    if isinstance(node, Arith):
        # Арифметика едет в той же записи, что понимает компилятор выражений:
        # операция и список доводов. Отдельного языка для неё не заводится.
        out = {"op": node.op, "args": [to_json(a) for a in node.args]}
        if node.zero is not None:
            out["on_zero"] = to_json(node.zero)
        return out
    if isinstance(node, Cmp):
        return {"op": node.op, "l": to_json(node.left), "r": to_json(node.right)}
    if isinstance(node, And):
        return {"op": "&", "p": [to_json(p) for p in node.parts]}
    if isinstance(node, Or):
        return {"op": "|", "p": [to_json(p) for p in node.parts]}
    if isinstance(node, Not):
        return {"op": "!", "e": to_json(node.expr)}
    if isinstance(node, IsNull):
        return {"op": "null", "e": to_json(node.ref)}
    if isinstance(node, TextExpr):
        return {"text": node.text}
    if isinstance(node, Template):
        return {"fmt": [to_json(p) for p in node.parts]}
    if isinstance(node, Aggregate):
        out = {"agg": node.kind, "model": node.model_name}
        if getattr(node, "via", None):
            out["via"] = node.via
        if node.domain is not None:
            out["domain"] = to_json(node.domain)
        if getattr(node, "of", None) is not None:
            out["of"] = to_json(node.of)
        if getattr(node, "on_empty", None) is not None:
            out["on_empty"] = to_json(node.on_empty)
        return out
    if isinstance(node, Order):
        return {"order": to_json(node.ref), "dir": node.direction}

    if isinstance(node, (list, tuple)):
        return [to_json(x) for x in node]

    raise DslError(
        f"{type(node).__name__} не умеет ехать в документ вида. "
        "Домен собирается из record./view., сравнений, &, |, ~ и .is_null()."
    )


def from_json(data):
    """Обратное преобразование. Нужно серверу и круговым тестам."""
    if data is None or isinstance(data, _SCALARS):
        return data
    if isinstance(data, list):
        return [from_json(x) for x in data]
    if not isinstance(data, dict):
        raise DslError(f"Не выражение: {data!r}")

    if data.get("unset") is True:
        return UNSET
    if "r" in data and "op" not in data:
        return RecordFieldRef(data["r"])
    if "v" in data:
        return ViewFieldRef(data["v"])
    if "i" in data:
        return ItemFieldRef(data["i"])
    if "lookup" in data:
        return _Lookup(data["lookup"], from_json(data["key"]), from_json(data["get"]))
    if "fmt" in data:
        return Template([from_json(p) for p in data["fmt"]])
    if set(data) == {"text"}:
        return TextExpr(data["text"])
    if "agg" in data:
        cls = {"count": Count, "exists": Exists,
               "sum": Sum, "min": Min, "max": Max}[data["agg"]]
        domain, of = data.get("domain"), data.get("of")
        empty = data.get("on_empty")
        return cls(data["model"], None if domain is None else from_json(domain),
                   via=data.get("via"), of=None if of is None else from_json(of),
                   on_empty=None if empty is None else from_json(empty))
    if "order" in data:
        return Order(from_json(data["order"]), data.get("dir", "asc"))

    if "args" in data and "op" in data:
        node = Round(from_json(data["args"][0])) if data["op"] == "round" else \
            Arith(data["op"], [from_json(a) for a in data["args"]])
        if "on_zero" in data:
            node = Arith(node.op, node.args, zero=from_json(data["on_zero"]))
        return node
    op = data.get("op")
    if op in Cmp.OPS:
        return Cmp(op, from_json(data["l"]), from_json(data["r"]))
    if op == "&":
        return And(*[from_json(p) for p in data["p"]])
    if op == "|":
        return Or(*[from_json(p) for p in data["p"]])
    if op == "!":
        return Not(from_json(data["e"]))
    if op == "null":
        return IsNull(from_json(data["e"]))

    raise DslError(f"Неизвестная операция {op!r} в выражении.")
