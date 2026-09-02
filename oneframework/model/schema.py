"""Модель как данные.

Объявление модели -- это питон, но его смысл переносим: имя поля, тип, подпись,
обязательность, связь, виджет. Здесь оно превращается в документ, который может
прочитать бэкенд на любом языке и фронтенд для подсказок.

Собирается интроспекцией, а не перечислением: у поля берётся всё, что оно про
себя объявило. Так новый тип поля попадает в схему сам, без правки этого файла --
а перечисление рано или поздно отстало бы молча.
"""

from __future__ import annotations

from .fields import Field

__all__ = ["model_schema", "app_schema"]

#: Служебное: к смыслу поля не относится и в документ не едет.
_SKIP = {"_order", "_explicit_default", "owner", "name", "default_widget",
         "widgets", "label", "required", "help"}



def field_schema(field):
    """Одно поле -> словарь. Пустые и умолчания опускаются, чтобы не шуметь."""
    out = {"name": field.name, "ftype": field.ftype}

    if field.label:
        out["label"] = field.label
    if field.required:
        out["required"] = True
    if field.help:
        out["help"] = field.help

    # `compute=` бывает **выражением**, а не именем действия: формула пишется
    # на языке приложения, а в документ едет деревом. Печатается здесь, потому
    # что общий обход ниже везёт значения как есть и узел выражения не понял бы.
    compute = getattr(field, "compute", None)
    if compute is not None and not isinstance(compute, (str, dict)):
        from .exprjson import to_json

        out["compute"] = to_json(compute)

    default = getattr(field, "_explicit_default", None)
    if default is not None and not callable(default):
        out["default"] = default

    # Виджет едет, только если отличается от умолчания своего типа: список
    # допустимых виджетов -- свойство типа и лежит в разделе "types" один раз.
    if field.default_widget != type(field).default_widget:
        out["widget"] = field.default_widget
    if not field.stored:
        out["stored"] = False

    # всё остальное, что поле объявило о себе: accept, digits, unit, comodel,
    # ondelete, inverse, semantic, lines, maximum, currency...
    for key, value in sorted(vars(field).items()):
        if key in _SKIP or key in out or key.startswith("_"):
            continue
        if value is None or value is False:
            continue
        out[key] = _plain(value)

    # Имя таблицы связи, если его закрепили руками. Хранится оно в `_relation`,
    # а всё подчёркнутое цикл выше пропускает как служебное -- и закреплённое
    # имя терялось бы молча: другой бэкенд собрал бы имя по умолчанию и полез в
    # другую таблицу. Тот же самый род потери, что и домен, не доехавший в
    # документ вида.
    pinned = getattr(field, "_relation", None)
    if pinned:
        out["relation_table"] = pinned

    return out


def _plain(value):
    """Ссылки на классы моделей едут именем, а не объектом."""
    if isinstance(value, type):
        return value.__name__
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def model_schema(model):
    """Модель -> документ. Автополя id/created_at/updated_at входят: они
    настоящие колонки, и другой бэкенд обязан о них знать.

    ``label`` -- подпись модели для человека. Без неё документ объявляет себя
    пригодным для другого бэкенда, а тот не может узнать, как модель зовётся на
    экране: пока приложение собирает питон, подпись берётся с класса, и потери
    не видно.
    """
    declared = sorted(model._fields.values(), key=lambda f: f._order)
    return {
        "name": model.__name__,
        "label": model._label,
        "table": model._table,
        "fields": [field_schema(f) for f in declared],
    }


def type_schema(models):
    """Свойства типов полей -- один раз на приложение, а не на каждое поле."""
    seen, out = set(), {}
    for m in models:
        for f in m._fields.values():
            if f.ftype in seen:
                continue
            seen.add(f.ftype)
            out[f.ftype] = {
                "sql": f.sql_type,
                "widget": type(f).default_widget,
                "widgets": list(f.widgets),
                # С класса, а не с экземпляра: здесь описан **тип**, и
                # `compute=` у одного поля не отменяет колонку у всех
                # остальных полей того же типа. Промах здесь виден не сразу --
                # у второй стороны просто перестаёт существовать колонка.
                "stored": type(f).stored,
            }
    return out


def app_schema(app):
    """Все модели приложения -> документ, годный для другого бэкенда."""
    models = getattr(app, "models", None) or getattr(app, "_models", [])
    if isinstance(models, dict):
        models = list(models.values())
    return {
        "version": 1,
        "types": type_schema(models),
        "models": [model_schema(m) for m in models],
    }
