"""Что обязаны знать одинаково **все** языки."""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["system_fields", "table_name", "TABLE_PATH", "load"]

#: Копия таблицы **внутри пакета**, а не файл над ним.
TABLE_PATH = Path(__file__).resolve().parent / "field-types.json"


VERSION = 1

#: Поля, которые модель получает даром, в том порядке, в каком их заводит
#: :class:`~oneframework.model.meta.ModelMeta`.
SYSTEM_FIELD_ORDER = ("id", "hlc", "created_at", "updated_at")

_ПРОБА = "__проба__"

def system_fields():
    from .model.meta import Model
    from .model.schema import field_schema

    class _Проба(Model):
        pass

    return {name: field_schema(_Проба._fields[name]) for name in SYSTEM_FIELD_ORDER}

def table_name(cls_name: str) -> str:
    """``TodoLine`` -> ``todo_line``. Правило одно на все языки."""
    from .model.meta import table_name as _t

    return _t(cls_name)

def load():
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))
