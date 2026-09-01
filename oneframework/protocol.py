"""Что обязаны знать одинаково **все** языки.

Библиотека на Kotlin и библиотека на JavaScript порождают те же документы, что
и питоновская: тот же документ модели, тот же документ вида, тот же отпечаток.
Значит где-то должно лежать знание, из которого эти документы собираются, --
какая у типа колонка, какой виджет по умолчанию, какие поля модель получает
даром.

Записать это знание в каждой библиотеке заново -- значит завести три копии
одного правила. Копии расходятся: не сразу, а на одиннадцатом типе поля,
который кто-то добавил в питон и забыл в Kotlin. Расхождение при этом тихое --
приложение соберётся, просто у него будет другой отпечаток вида, и обмен
сочтёт два одинаковых приложения разными.

Поэтому знание одно и лежит **данными**: ``protocol/field-types.json``. Питон
его порождает интроспекцией своих же классов полей, остальные языки читают.
Сторожит совпадение ``tests/test_protocol.py``: добавили тип поля, не
пересобрав таблицу, -- тест падает.

Порождается, а не пишется руками, по той же причине, по которой
:mod:`oneframework.model.schema` собирает документ интроспекцией: перечисление
однажды отстанет молча.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

__all__ = ["field_types", "system_fields", "table_name", "TABLE_PATH", "load"]

#: Файл договора. Рядом с остальными -- `document.json`, `logic.json`, `wire.json`.
TABLE_PATH = Path(__file__).resolve().parents[1] / "protocol" / "field-types.json"

#: Версия договора. Растёт, когда меняется **форма** таблицы, а не её
#: содержимое: новый тип поля версию не двигает, новый ключ у типа -- двигает.
VERSION = 1

#: Поля, которые модель получает даром, в том порядке, в каком их заводит
#: :class:`~oneframework.model.meta.ModelMeta`. Порядок здесь -- не оформление:
#: документ модели печатает поля по нему, а отпечаток считается от документа.
SYSTEM_FIELD_ORDER = ("id", "hlc", "created_at", "updated_at")

#: Имя связанной модели у пробного поля. Ссылочному полю без неё не создаться,
#: а в договоре ей делать нечего -- по этой метке она оттуда и вычищается.
_ПРОБА = "__проба__"


def field_types():
    """Таблица типов: что известно о типе поля, а не об отдельном поле.

    ``defaults`` -- то, что попадает в документ модели у поля, объявленного без
    единого аргумента. У строки это ``lines`` и ``semantic``, у денег -- валюта
    и точность. Библиотека на другом языке берёт их отсюда и не выдумывает.
    """
    from .model import fields as F
    from .model.schema import field_schema

    out = {}
    for name, cls in sorted(vars(F).items()):
        if not (inspect.isclass(cls) and issubclass(cls, F.Field)):
            continue
        if cls is F.Field:
            continue
        entry = {
            "sql": cls.sql_type,
            "widget": cls.default_widget,
            "widgets": list(cls.widgets),
            "stored": bool(cls.stored),
        }
        defaults = _defaults_of(cls, field_schema)
        if defaults:
            entry["defaults"] = defaults
        semantics = getattr(cls, "SEMANTICS", None)
        if semantics:
            entry["semantics"] = list(semantics)
        # Тип, а не класс: `Uuid` -- это `String` с другим `ftype`, и в
        # документе стоит ftype. Два класса с одним ftype -- ошибка объявления,
        # и пусть она будет видна здесь, а не в разошедшемся отпечатке.
        if cls.ftype in out and out[cls.ftype] != entry:
            raise RuntimeError(
                f"Два класса поля с ftype={cls.ftype!r} описывают тип по-разному: "
                f"{out[cls.ftype]} против {entry}."
            )
        out[cls.ftype] = entry
    return out


def _defaults_of(cls, field_schema):
    """Что поле этого типа печатает о себе, будучи объявлено без аргументов.

    Спрашивается у самого поля, а не перечисляется: у ``Monetary`` это валюта и
    точность, и никто не обязан помнить про них, добавляя тип.

    Типы, которым нужен обязательный аргумент (``Selection``, ``One2many``),
    умолчаний не дают -- и не должны: у них нет вида «без аргументов».
    """
    try:
        field = cls(_ПРОБА) if _needs_comodel(cls) else cls()
    except TypeError:
        return {}
    field.name = "x"
    field.owner = None
    doc = field_schema(field)
    # Связанная модель -- не умолчание типа, а то, что назвали при объявлении.
    # Сюда она попала только потому, что без неё поле не создать; оставить её
    # значило бы записать в договор выдуманное имя модели.
    return {k: v for k, v in doc.items()
            if k not in ("name", "ftype") and v != _ПРОБА}


def _needs_comodel(cls):
    params = list(inspect.signature(cls.__init__).parameters.values())[1:]
    return bool(params) and params[0].name == "comodel"


def system_fields():
    """Документы четырёх даровых полей -- ровно те, что печатает питон.

    Отдаются документом, а не описанием, потому что другому языку нужен именно
    документ: он его допишет к объявленным полям и получит тот же отпечаток.
    """
    from .model.meta import Model
    from .model.schema import field_schema

    class _Проба(Model):
        pass

    return {name: field_schema(_Проба._fields[name]) for name in SYSTEM_FIELD_ORDER}


def table_name(cls_name: str) -> str:
    """``TodoLine`` -> ``todo_line``. Правило одно на все языки."""
    from .model.meta import table_name as _t

    return _t(cls_name)


def document():
    """Вся таблица целиком -- то, что лежит в ``protocol/field-types.json``."""
    return {
        "$comment": (
            "Что все языки обязаны знать о полях одинаково. Порождается "
            "oneframework.protocol.document(), сторожится tests/test_protocol.py. "
            "Руками не править: правка уедет при первой пересборке."
        ),
        "version": VERSION,
        "types": field_types(),
        "system_fields": system_fields(),
        "system_field_order": list(SYSTEM_FIELD_ORDER),
    }


def load():
    """Прочитать закреплённую таблицу. Ею пользуются сборка и тесты."""
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))


def write():
    """Пересобрать файл договора. Зовётся тестом и командой ``protocol``."""
    text = json.dumps(document(), ensure_ascii=False, indent=2) + "\n"
    TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TABLE_PATH.write_text(text, encoding="utf-8")
    return TABLE_PATH


if __name__ == "__main__":  # pragma: no cover - ручная пересборка
    print(write())
