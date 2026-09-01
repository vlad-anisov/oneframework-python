"""Договор о полях и о пакете объявления.

Таблица типов порождается из питоновских классов полей, а читают её три языка.
Значит расходиться она может ровно одним способом: кто-то добавил тип поля и
не пересобрал файл. Здесь это и ловится.

Второй тест -- о сборке: приложение, собранное из питоновских классов, и то же
приложение, собранное из пакета объявления, обязаны дать одну и ту же схему.
Правило создания таблиц записано в двух местах (классы и документы), и это
осознанный долг; сторож у него -- этот тест.

Каждый пример читается **отдельным процессом**. Не из осторожности: реестр
моделей глобален и ключуется именем класса, а ``Task`` есть в трёх примерах из
пяти. Загрузи их в один процесс -- и связи начнут разрешаться в чужой класс,
причём молча. Тот же довод записан в ``tests/test_document.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from oneframework import protocol

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ["notes-python", "todo", "showcase", "kitchen", "gtasks"]

#: Собрать один пример двумя счётами и вернуть, что получилось.
#:
#: Слева -- питоновские классы моделей (`app_schema`, `App.meta`), справа --
#: документы из пакета объявления, то есть ровно то, что приезжает от Kotlin и
#: JavaScript. Раньше слева стоял `build_plan(app)`, но дорога в план теперь
#: одна -- через пакет, -- и сравнение вышло бы само с собой. Второй счёт
#: остался тем же: он считает по объектам, не заглядывая в пакет.
_COLLECT = r"""
import json, sys, tempfile
sys.path.insert(0, sys.argv[1])
from pathlib import Path

from oneframework.cli.plan import build_plan
from oneframework.cli.sources import from_python
from oneframework.declaration import Bundle, declare
from oneframework.model.schema import app_schema

app = from_python(Path(sys.argv[2]))
bundle = Bundle(declare(app))
# Схема -- **план**, а не DDL: таблицы заводит один `db.ensureSchema` на
# стороне JS, и оба счёта обязаны привести к нему с одинаковым описанием.
print(json.dumps({
    "schema_from_classes": app_schema(app),
    "schema_from_bundle": build_plan(bundle)["schema"],
    "meta_from_app": app.meta(),
    "meta_from_bundle": bundle.meta(),
}, ensure_ascii=False, default=str))
"""


def collect(example):
    directory = ROOT / "examples" / example
    out = subprocess.run(
        [sys.executable, "-c", _COLLECT, str(directory), str(directory / "app.py")],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_type_table_is_up_to_date():
    """Файл договора обязан совпадать с тем, что говорят классы полей."""
    записано = json.loads(protocol.TABLE_PATH.read_text(encoding="utf-8"))
    assert записано == protocol.document(), (
        "protocol/field-types.json отстал от классов полей. "
        "Пересоберите: python3 -m oneframework.protocol"
    )


def test_every_field_type_is_in_the_table():
    """Ни один тип поля не должен потеряться по дороге в договор."""
    from oneframework.model.fields import FIELD_TYPES

    таблица = protocol.field_types()
    пропали = sorted(set(FIELD_TYPES) - set(таблица))
    assert not пропали, f"типы полей без описания в договоре: {пропали}"


@pytest.mark.parametrize("example", EXAMPLES)
def test_schema_from_a_bundle_matches_schema_from_classes(example):
    """Две дороги к одной схеме обязаны привести в одно место.

    Разойдись они, и приложение на другом языке получило бы другую таблицу --
    молча, потому что SQLite создаст любую.

    Сравнивается **описание**, а не DDL. До 21.08.2026 правило создания таблиц
    было записано трижды: у классов (`Database.ensure_schema`), у пакета
    (`Bundle.ensure_schema`) и на устройстве. Две питоновские записи удалены;
    таблицы заводит одна -- `db.ensureSchema` на JS, -- и обе дороги теперь
    обязаны прийти к ней с одинаковым описанием.
    """
    собрано = collect(example)
    assert собрано["schema_from_classes"] == собрано["schema_from_bundle"]


@pytest.mark.parametrize("example", EXAMPLES)
def test_bundle_metadata_matches_the_python_app(example):
    """Сведения, которые рантайм читает до базы, тоже обязаны совпасть.

    Их пакет не везёт -- он их **выводит** из типов и моделей. Вывод обязан
    совпасть с тем, что говорит питоновское приложение, иначе на устройстве
    поле подпишется иначе или карточка нарисует поля в другом порядке.
    """
    собрано = collect(example)
    assert собрано["meta_from_app"] == собрано["meta_from_bundle"]


def test_every_exported_name_exists():
    """``__all__`` -- обещание, а не украшение.

    Имя, обещанное списком и не существующее в модуле, роняет
    ``from module import *`` на первом же и не ловится ничем: обычный ввоз по
    имени такого списка не читает. Нашлось разбором со стороны 20.08.2026 --
    в ``oneframework.wasm.store`` девять имён пережили удаление рантайма WASM
    и остались обещанием.
    """
    import importlib
    import pkgutil

    import oneframework

    ложные = {}
    for найдено in pkgutil.walk_packages(oneframework.__path__, "oneframework."):
        модуль = importlib.import_module(найдено.name)
        нет = [имя for имя in getattr(модуль, "__all__", ()) if not hasattr(модуль, имя)]
        if нет:
            ложные[найдено.name] = нет
    assert not ложные, f"обещано в __all__, но не существует: {ложные}"
