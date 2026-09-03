"""Действие, объявленное данными: правило + запись, без единого байта кода.

«Завершить задачу вместе с подзадачами на любую глубину» выражается так же,
как выражался бы модулем: правило даёт множество, `Mutation` его правит, и всё
это один оператор SQL. Разница в том, что в модуле условие приходится
вычитывать из цикла, а здесь оно стоит строкой объявления.

Форма объявления::

    {"name": "Task.complete", "model": "Task",
     "rule":  {"name": "subtree", "table": "task", "via": "parent_id",
               "include_seed": True, "seed": {"param": "root"},
               "where": {"op": "not", "args": [{"field": "done"}]}},
     "write": {"table": "task", "source": "subtree",
               "set": {"done": {"const": True}}},
     "returns": [{"name": "completed", "type": "integer"}]}
"""

from __future__ import annotations

from ..errors import OneFrameworkError

#: Исполнителей здесь нет и не должно быть: действие исполняет устройство
#: (`libs/js/src/core/runtime/logic.js`), правила -- в
#: `tests/js/logic-host.test.mjs`. Здесь только различение **формы**
#: объявления: его спрашивает выкладка, решая, что класть в базу.
__all__ = ["is_declarative", "is_python", "is_js", "is_wasm"]


def is_declarative(doc):
    """Объявление это или имя точки входа в модуль. Различает **форма**."""
    return isinstance(doc, dict) and "entry" not in doc and (
        "rule" in doc or "write" in doc or is_python(doc) or is_js(doc)
        or is_wasm(doc))


def is_python(doc):
    """Действие, которое считает **настоящий питон на устройстве**.

    Ради того, чего в SQL нет и не будет: словарной морфологии, разбора чужого
    формата. Всё остальное обязано быть правилом и правкой -- питон здесь не
    лазейка, а ответ на «этого запросом не выразить».

    Едет **исходником**, той же дорогой, что модели и виды: байты пришлось бы
    собирать, подписывать и сверять.
    """
    return isinstance(doc, dict) and isinstance(doc.get("python"), dict) \
        and "source" in doc["python"]


def is_wasm(doc):
    """Действие, **скомпилированное** в WebAssembly.

    Ни интерпретатора в поставке, ни исходника на устройстве: туда едет
    модуль, и его инстанцирует движок, который в webview уже есть. Объявление
    называет **модуль**, а не текст -- байты кладёт сборка, потому что 624 КБ
    машинного кода строкой в таблице определений возить незачем.
    """
    return isinstance(doc, dict) and isinstance(doc.get("wasm"), dict) \
        and "module" in doc["wasm"]




def is_js(doc):
    """Действие на JavaScript -- самая дешёвая из трёх дорог.

    Рантайма закладывать не надо: он уже стоит, это сам webview.

    Kotlin сюда **не** приезжает: `.kt` объявлен как ``wasm``, компилируется
    TeaVM в WebAssembly и исполняется `wasm_action.js`. ``language`` говорит,
    чем действие написано, а не чем исполняется.
    """
    return isinstance(doc, dict) and isinstance(doc.get("js"), dict) \
        and "source" in doc["js"]


