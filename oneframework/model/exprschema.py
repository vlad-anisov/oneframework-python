"""Грамматика выражений: одно описание вместо пяти.

Дерево выражения -- единственная структура, общая трём языкам объявления и
двум вычислителям, и до сих пор у неё не было файла. Форма узлов жила прозой в
пяти местах сразу (докстрока :mod:`~oneframework.model.exprjson`,
``libs/js/src/expr.mjs``, ``libs/kotlin/.../Expr.kt``, ``libs/js/src/core/expr.js``,
``docs/wasm-api.md``), и половина узлов не была описана нигде: они
существовали только телом :func:`~oneframework.model.exprjson.to_json`.

Цена пяти описаний -- не путаница в чтении, а молчание: узел, которого чужая
библиотека не знает, доезжает не ошибкой, а не тем условием, то есть не тем
списком на экране. Заметить это можно только по чужой жалобе.

Поэтому описание одно и лежит данными -- ``protocol/expression.json``, рядом с
остальными договорами. Оно **порождается**, а не пишется руками: формы
получаются прогоном настоящего ``to_json`` по образцу каждого узла, слова
арифметики -- разбором самого кода. Написанный руками перечень был бы шестым
описанием -- тем, которое отстанет первым и молча.

**Почему модуль остаётся, хотя каркас его не ввозит** (пересмотрено 21.08.2026,
когда убирали всё, что держали одни проверки). Он не двойник и не эталон: он
**порождает** `protocol/expression.json` -- договор, который читают
`libs/js/src/expr.mjs`, драйвер грамматики и сама сюита. Каркас не ввозит его по
той же причине, по какой не ввозит `oneframework.protocol`: договор
пересобирается командой, а не на запуске.

Удалить его значило бы вернуться к пяти описаниям -- ровно к тому, от чего он и
заводился.

Здесь же живёт :func:`problems` -- обход, который сверяет чужое дерево с этим
файлом. Правил в нём нет ни одного: все правила -- в файле, а обход только
ходит по ним. Иначе договор снова оказался бы записан дважды.
"""

from __future__ import annotations

import ast
import builtins
import json
from pathlib import Path

from . import exprjson
from .expr import (
    UNSET, Aggregate, And, Arith, Cmp, IsNull, ItemFieldRef, Not, Or,
    RecordFieldRef, Round, Sum, Template, TextExpr, ViewFieldRef, _Lookup,
)
from .exprjson import _SCALARS, to_json

__all__ = ["PATH", "VERSION", "arith_words", "branch_classes", "document",
           "load", "match", "problems", "samples", "write"]

#: Файл договора. Рядом с остальными -- `document.json`, `field-types.json`.
PATH = Path(__file__).resolve().parents[2] / "protocol" / "expression.json"

#: Версия договора. Растёт, когда меняется **форма** описания, а не его
#: содержимое: новый узел версию не двигает, новый вид ключа -- двигает.
VERSION = 1

#: Сентинелы образца. Всё, что в образце стоит на этом месте, -- дырка, а не
#: значение: ``<имя>`` -- имя поля или модели, ``<узел>`` -- любое вложенное
#: выражение. Они же лежат в файле: чужая библиотека собирает по образцу свой
#: узел и сверяется побайтно, не угадывая, что здесь имя, а что поддерево.
NAME = "<имя>"
CHILD = RecordFieldRef("<узел>")

#: Свободный текст -- не имя и не узел. Заведён для выражения, записанного
#: строкой: без своего сентинела разбор формы принял бы образцы за перечень
#: допустимых строк, и договор объявил бы законными ровно их.
TEXT = "<текст>"

#: Питоновский тип литерала -> как он называется в JSON. Литерал -- тоже
#: выражение: ``record.tag == 3`` везёт тройку собой, без обёртки.
_JSON_TYPE = {bool: "boolean", int: "number", float: "number",
              str: "string", type(None): "null"}


def arith_words():
    """Слова арифметики -- те, что питон умеет породить, и никакие другие.

    Берутся разбором кода пакета: ``Arith("length", ...)`` где угодно в дереве
    -- это слово языка. Перечислять их руками нельзя: словарь растёт по одной
    строке в разных модулях (``len()`` -- в одном месте, ``.lower()`` -- в
    другом, ``if`` -- в третьем), и перечень отстанет молча.

    Предел приёма честный: слово, собранное на исполнении (``Arith(op, ...)``
    с переменной), сюда не попадёт. Сегодня таких нет ни одного.
    """
    words = {Round(0).op}
    package = Path(__file__).resolve().parents[1]
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            if getattr(node.func, "id", None) != "Arith":
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                words.add(first.value)
    return sorted(words)


def branch_classes():
    """Узлы, которые ``to_json`` разбирает своими ветками, -- из его же кода.

    Разбором, а не перечислением: перечень веток был бы ещё одним описанием, и
    отстал бы он ровно тогда, когда кто-то заведёт новый узел, -- то есть в
    единственную минуту, когда сторож и нужен.

    Литералы и списки JSON везёт собой, узлами они не становятся -- поэтому в
    ответе только классы пакета.
    """
    tree = ast.parse(Path(exprjson.__file__).read_text(encoding="utf-8"))
    printer = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "to_json")
    names = set()
    for node in ast.walk(printer):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "isinstance":
            target = node.args[1]
            parts = target.elts if isinstance(target, ast.Tuple) else [target]
            names |= {p.id for p in parts if isinstance(p, ast.Name)}
    found = set()
    for name in names:
        value = vars(exprjson).get(name, vars(builtins).get(name))
        found |= set(value) if isinstance(value, tuple) else {value}
    return {c for c in found
            if isinstance(c, type) and c.__module__.startswith("oneframework")}


def samples():
    """По образцу на каждую ветку ``to_json``, вариантами.

    Вариантов несколько там, где форма узлом не исчерпывается: у сравнения
    ключ ``op`` перебирает шесть слов, у агрегата их пять, а ключей у него на
    четыре больше, когда домен, колонка и ответ на пустом наборе объявлены.
    Что в ключе постоянно, а что перебирается, видно только по нескольким
    образцам сразу -- по одному не отличить перечень от постоянного слова.
    """
    aggregates = sorted(Aggregate.__subclasses__(), key=lambda cls: cls.kind)
    return {
        "unset": [UNSET],
        "record_ref": [RecordFieldRef(NAME)],
        "view_ref": [ViewFieldRef(NAME)],
        "item_ref": [ItemFieldRef(NAME)],
        "lookup": [_Lookup(NAME, CHILD, CHILD)],
        "cmp": [Cmp(op, CHILD, CHILD) for op in sorted(Cmp.OPS)],
        "and": [And(CHILD, CHILD)],
        "or": [Or(CHILD, CHILD)],
        "not": [Not(CHILD)],
        "is_null": [IsNull(CHILD)],
        # ``round`` едет своим классом и с одним доводом -- остальные слова
        # арифметики берут два: сколько их, форма узла не описывает.
        "arith": [Round(CHILD) if word == Round(0).op else Arith(word, [CHILD, CHILD])
                  for word in arith_words()]
                 + [Arith("/", [CHILD, CHILD], zero=CHILD)],
        # Узел только на проводе: разворачивает его сборка, до устройства
        # строка не доезжает. В образце он ради того, чтобы договор описывал
        # и его -- привязки на него смотрят.
        "text": [TextExpr(TEXT)],
        "template": [Template([CHILD, CHILD])],
        "aggregate": [cls(NAME) for cls in aggregates]
                     + [Sum(NAME, CHILD, via=NAME, of=CHILD, on_empty=CHILD)],
        "order": [CHILD.asc(), CHILD.desc()],
    }


def document():
    """Весь договор целиком -- то, что лежит в ``protocol/expression.json``."""
    return {
        "$comment": (
            "Грамматика выражений: какие узлы бывают и как каждый записан. "
            "Одно дерево на три языка объявления и на оба вычислителя. "
            "Литерал -- тоже выражение, список -- перечень выражений (sort=). "
            "Порождается oneframework.model.exprschema.document(), сторожится "
            "tests/test_expression_grammar.py. Руками не править: правка "
            "уедет при первой пересборке."
        ),
        "version": VERSION,
        "sentinels": {"name": NAME, "child": to_json(CHILD), "text": TEXT},
        "literals": sorted({_JSON_TYPE[t] for t in _SCALARS}),
        "nodes": {name: _shape(variants)
                  for name, variants in samples().items()},
    }


def _shape(variants):
    """Форма узла -- из прогона ``to_json``, а не из пересказа его веток."""
    forms = [to_json(v) for v in variants]
    always = set(forms[0]).intersection(*(set(f) for f in forms))
    seen = {}
    for form in forms:
        for key, value in form.items():
            seen.setdefault(key, []).append(value)
    keys = {}
    for key, values in seen.items():
        holds = _holds(values)
        if key not in always:
            holds["optional"] = True
        keys[key] = holds
    return {"keys": keys, "sample": forms[0]}


def _holds(values):
    """Что несёт ключ. Узнаётся по сентинелу, а не по имени ключа."""
    child = to_json(CHILD)
    if all(v == child for v in values):
        return {"expr": True}
    if all(isinstance(v, list) and v and all(x == child for x in v)
           for v in values):
        return {"exprs": True}
    if all(v == NAME for v in values):
        return {"name": True}
    if all(v == TEXT for v in values):
        return {"text": True}
    return {"one_of": sorted(set(values), key=repr)}


def load():
    """Прочитать закреплённую грамматику. Ею пользуются сторожа и драйверы."""
    return json.loads(PATH.read_text(encoding="utf-8"))


def match(node, grammar=None):
    """Как называется узел такой формы. ``None`` -- в грамматике такого нет.

    ``None`` отвечается и на «подошло сразу несколько»: неразличимые формы --
    это не грамматика, а гадание, и читающая сторона выберет любую.
    """
    grammar = load() if grammar is None else grammar
    fits = _fits(node, grammar)
    return fits[0] if len(fits) == 1 else None


def _fits(node, grammar):
    return [name for name, shape in grammar["nodes"].items()
            if _matches(node, shape["keys"])]


def problems(node, grammar=None, path="выражение"):
    """Чем дерево расходится с грамматикой. Пустой список -- сходится.

    Отвечает списком, а не отказом: у чужого дерева расхождений бывает
    несколько, и чинить их по одному, узнавая о следующем только после
    починки предыдущего, -- худший способ узнать, насколько язык отстал.
    """
    grammar = load() if grammar is None else grammar
    if isinstance(node, list):
        return [p for i, item in enumerate(node)
                for p in problems(item, grammar, f"{path}[{i}]")]
    if not isinstance(node, dict):
        kind = _JSON_TYPE.get(type(node))
        if kind is None or kind not in grammar["literals"]:
            return [f"{path}: {node!r} -- не литерал языка"]
        return []

    fits = _fits(node, grammar)
    if not fits:
        return [f"{path}: узла такой формы в грамматике нет: {sorted(node)}"]
    if len(fits) > 1:
        return [f"{path}: форма подошла сразу нескольким узлам: {fits}"]

    keys = grammar["nodes"][fits[0]]["keys"]
    bad = []
    for key, value in node.items():
        holds, where = keys[key], f"{path}.{key}"
        if holds.get("expr"):
            bad += problems(value, grammar, where)
        elif holds.get("exprs"):
            if not isinstance(value, list):
                bad.append(f"{where}: ожидался список выражений, а не {value!r}")
            else:
                bad += [p for i, item in enumerate(value)
                        for p in problems(item, grammar, f"{where}[{i}]")]
        elif holds.get("name") and not isinstance(value, str):
            bad.append(f"{where}: имя обязано быть строкой, а не {value!r}")
        elif "one_of" in holds and value not in holds["one_of"]:
            bad.append(f"{where}: {value!r} -- не из {holds['one_of']}")
    return bad


def _matches(node, keys):
    """Узел узнаётся по набору ключей и по постоянным словам в них.

    Лишний ключ -- не мелочь, а другой узел: ``{"r": "тег"}`` -- ссылка, а
    ``{"op": "=", "l": ..., "r": ...}`` -- сравнение, и различает их ровно
    это. Поэтому «подошло сразу несколько» -- тоже расхождение: значит формы
    неразличимы, и читающая сторона выберет любую.
    """
    if set(node) - set(keys):
        return False
    if {k for k, h in keys.items() if not h.get("optional")} - set(node):
        return False
    return all(node[k] in h["one_of"]
               for k, h in keys.items() if "one_of" in h and k in node)


def write():
    """Пересобрать файл договора: ``python3 -m oneframework.model.exprschema``.

    Сторож файл не пересобирает, а сверяет: пересборка молча заменила бы
    расхождение обновлением, и договор стал бы отражением кода, а не условием
    для него.
    """
    text = json.dumps(document(), ensure_ascii=False, indent=2) + "\n"
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(text, encoding="utf-8")
    return PATH


if __name__ == "__main__":  # pragma: no cover - ручная пересборка
    print(write())
