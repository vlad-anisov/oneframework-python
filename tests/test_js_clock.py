"""Ключ записи: питон печатает, устройство читает -- и наоборот.

Ключ обязан сортироваться как время создания, а отметка -- как обычная строка.
Ни то, ни другое не сломается с ошибкой: неверный ключ даст перемешанный
список, неверная отметка -- проигранный спор при слиянии и молча исчезнувшую
чужую правку.

**Сторона одна.** Файл назывался `test_js_clock_parity.py` и сверял питоновские
часы с теми, что на устройстве.

Откуда теперь ожидания, раз соседа нет:

* **форма отметки** -- формулой (`ожидаемая`). Это спецификация, записанная
  отдельно от реализации: год-месяц-день, миллисекунды тремя знаками, счётчик
  четырьмя шестнадцатеричными, узел восемью. Совпадение формулы с прежними
  питоновскими часами проверено перед переносом;
* **сценарий** -- замороженными строками (`СЫГРАНО`, `ПЕРЕЗАПУСКИ`). Они сняты
  с проверенной реализации в день переноса и с тех пор являются договором: их
  меняют вместе с форматом отметки и не иначе;
* **отказы** -- словами. Текст отказа -- то единственное, чем он полезен.
"""

import json
import re
import time
from pathlib import Path

import pytest
from conftest import needs_node, run_node

from oneframework.model.ids import is_id, new_id

ROOT = Path(__file__).resolve().parents[1]
IDS_JS = ROOT / "libs" / "js" / "src" / "core" / "runtime" / "ids.js"
HLC_JS = ROOT / "libs" / "js" / "src" / "core" / "runtime" / "hlc.js"

HOW_MANY = 10_000

#: Ровно то, что описано в oneframework/model/ids.py: седьмая версия и вариант RFC.
UUID7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

#: Ширина частей фиксирована -- на этом держится сравнение отметок строкой.
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z-[0-9a-f]{4}-[0-9a-f]{8}$")


def rises(values):
    return all(a < b for a, b in zip(values, values[1:]))


# --------------------------------------------------------------------------
# ключи
# --------------------------------------------------------------------------
IDS_JS_RUNNER = """
import { readFileSync } from "node:fs";
import { newId, isId } from "%(ids)s";

const payload = JSON.parse(readFileSync(process.argv[2], "utf8"));
process.stdout.write(JSON.stringify({
  made: Array.from({ length: payload.howMany }, newId),
  known: payload.probes.map(isId),
}));
"""

#: Строки, про которые обе стороны обязаны ответить одинаково. Проверка нужна
#: миграции: ею она отличает уже переехавшую базу от той, где id ещё число.
PROBES = [
    "018f2b4c-1a2b-7c3d-8e4f-506172839405",
    "018F2B4C-1A2B-7C3D-8E4F-506172839405",             # регистр не важен
    "{018f2b4c-1a2b-7c3d-8e4f-506172839405}",           # длина уже не та
    "018f2b4c-1a2b-7c3d-8e4f-50617283940",              # на символ короче
    "018f2b4c-1a2b-7c3d-8e4f-50617283940z",             # не шестнадцатеричный
    "не-ключ-а-строка-длиной-ровно-тридцать",
    "", "42", None, 42, True, [],
]


def test_ten_thousand_keys_in_a_row_rise():
    """Строковый порядок ключей -- это `ORDER BY id`, и он обязан быть порядком
    добавления. Десять тысяч подряд -- это заведомо больше, чем влезает в
    двенадцатибитный счётчик одной миллисекунды."""
    assert rises([new_id() for _ in range(HOW_MANY)])


@needs_node
def test_javascript_keys_rise_too(tmp_path):
    payload = {"howMany": HOW_MANY, "probes": PROBES}
    answer = json.loads(run_node(tmp_path, IDS_JS_RUNNER % {"ids": IDS_JS}, payload))

    made = answer["made"]
    assert len(made) == HOW_MANY
    assert rises(made)
    assert all(UUID7.match(key) for key in made)


@needs_node
def test_both_sides_recognise_the_same_keys(tmp_path):
    payload = {"howMany": 8, "probes": PROBES + [new_id() for _ in range(4)]}
    answer = json.loads(run_node(tmp_path, IDS_JS_RUNNER % {"ids": IDS_JS}, payload))

    assert answer["known"] == [is_id(v) for v in payload["probes"]]
    # ...и ключи, сделанные JS, питон обязан принимать своими.
    assert all(is_id(key) for key in answer["made"])


@needs_node
def test_a_javascript_key_carries_the_time_where_python_reads_it(tmp_path):
    """Первые 48 бит -- миллисекунды. Не на своём месте они сломали бы не
    формат, а порядок: ключи двух рантаймов перестали бы вставать в один ряд."""
    made = json.loads(run_node(tmp_path, IDS_JS_RUNNER % {"ids": IDS_JS},
                               {"howMany": 1, "probes": []}))["made"][0]
    made_at = int(made.replace("-", "")[:12], 16) / 1000
    assert abs(made_at - time.time()) < 30


# --------------------------------------------------------------------------
# часы
# --------------------------------------------------------------------------
BASE = 1786786863118            # 2026-08-15T09:41:03.118Z
#: Сценарий часов переехал в `tests/js/hlc.test.mjs` вместе с ожиданиями:
#: они лежат данными в `tests/js/данные/hlc.json`, выгруженные отсюда. Правила
#: там те же -- побайтные отметки, посчитанные формулой формата, а не вызовом
#: проверяемой реализации.
#:
#: Здесь остаётся то, чего одной стороне не проверить: ключ, напечатанный
#: питоном, обязан читаться на устройстве, и наоборот.
