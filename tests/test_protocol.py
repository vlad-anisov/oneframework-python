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
#: JavaScript. Раньше слева стоял `план(app)`, но дорога в план теперь
#: одна -- через пакет, -- и сравнение вышло бы само с собой. Второй счёт
#: остался тем же: он считает по объектам, не заглядывая в пакет.
_COLLECT = r"""
import json, sys, tempfile
sys.path.insert(0, sys.argv[1])
# Каталог проверок -- ради `conftest`: план считает ядро. От рабочей папки, а
# не от `argv[1]`: там лежит пример, а не корень.
import os
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
from pathlib import Path

from conftest import план
from oneframework.__main__ import _приложение
from oneframework.declaration import Bundle, declare
from oneframework.model.schema import app_schema

app = _приложение(Path(sys.argv[2]))
bundle = Bundle(declare(app))
# Схема -- **план**, а не DDL: таблицы заводит один `db.ensureSchema` на
# стороне JS, и оба счёта обязаны привести к нему с одинаковым описанием.
print(json.dumps({
    "schema_from_classes": app_schema(app),
    "schema_from_bundle": план(bundle)["schema"],
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


def test_the_binding_declares_exactly_the_types_the_contract_names():
    """Состав типов у привязки и у договора -- один.

    Раньше здесь сверялись **значения**: файл договора против того, что говорят
    классы полей. Сверять их больше нечем и незачем -- классы
    берут колонку, виджеты и умолчания **из** этого файла, и сравнение
    сравнивало бы его с самим собой.

    Осталось то, что круговым не стало: состав. Класс, называющий тип, которого
    в договоре нет, отказывает при объявлении -- это ловит сам питон. А вот
    обратное, тип в договоре без класса у привязки, не заметил бы никто: она
    молча не умела бы его объявлять, и узналось бы это на чужом приложении.
    """
    from oneframework.model.fields import FIELD_TYPES

    в_договоре = set(protocol.load()["types"])
    у_привязки = set(FIELD_TYPES)
    assert у_привязки == в_договоре, (
        f"только у привязки: {sorted(у_привязки - в_договоре)}; "
        f"только в договоре: {sorted(в_договоре - у_привязки)}"
    )


def test_a_type_the_contract_does_not_name_is_refused():
    """Класс поля с типом мимо договора отказывает при объявлении.

    Иначе привязка завела бы у себя тип, которого два других языка не знают, и
    приложение с ним собралось бы -- а на устройстве поле оказалось бы без
    колонки и без виджета.
    """
    from oneframework.errors import DslError
    from oneframework.model.fields import Field

    with pytest.raises(DslError, match="field-types.json"):
        type("Выдуманное", (Field,), {"ftype": "нет-такого"})


@pytest.mark.parametrize("example", EXAMPLES)
def test_schema_from_a_bundle_matches_schema_from_classes(example):
    """Две дороги к одной схеме обязаны привести в одно место.

    Разойдись они, и приложение на другом языке получило бы другую таблицу --
    молча, потому что SQLite создаст любую.

    Сравнивается **описание**, а не DDL. Прежде правило создания таблиц
    было записано трижды: у классов (`Database.ensure_schema`), у пакета
    (`Bundle.ensure_schema`) и на устройстве. Две питоновские записи удалены;
    таблицы заводит одна -- `db.ensureSchema` на JS, -- и обе дороги теперь
    обязаны прийти к ней с одинаковым описанием.
    """
    # Тело формулы меткой: питоновский счёт видит её строкой, а счёт из пакета
    # -- развёрнутым деревом, и сверять их значило бы мерить работу разворота
    # (она сторожится в `tests/js/expr-text-wire.test.mjs`). Наличие формулы
    # сохраняется, поэтому потеря от нормализации не спрячется.
    def без_тела(о):
        if isinstance(о, dict):
            return {к: ("<формула>" if к == "compute" else без_тела(з)) for к, з in о.items()}
        return [без_тела(э) for э in о] if isinstance(о, list) else о

    собрано = collect(example)
    assert без_тела(собрано["schema_from_classes"]) == без_тела(собрано["schema_from_bundle"])


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
    имени такого списка не читает. Нашлось разбором со стороны --
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
