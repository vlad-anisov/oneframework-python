"""``Model`` -- declarative persisted entity."""

from __future__ import annotations

import re

from ..errors import DslError, did_you_mean
from .fields import MODEL_REGISTRY, Datetime, Field, Many2one, String, Uuid

__all__ = ["Model", "ModelMeta", "table_name"]

_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")

def table_name(cls_name: str) -> str:
    """``TodoLine`` -> ``todo_line``."""
    return _CAMEL.sub("_", cls_name).lower()

def _is_device_action(value):
    """Уже объявленное действие -- то, что вернул ``action(...)``."""
    return hasattr(value, "declaration") and hasattr(value, "writes")

def _actions_of(ns):
    import types

    out = []
    for name, value in ns.items():
        if _is_device_action(value):
            out.append(value)
        elif (isinstance(value, types.FunctionType)
                and not name.startswith("_")):
            from ..device import DeviceAction

            action = DeviceAction(value)
            action.__set_name__(None, name)
            out.append(action)
    return out

class ModelMeta(type):
    def __new__(mcls, name, bases, ns, **kw):
        cls = super().__new__(mcls, name, bases, dict(ns), **kw)
        if not any(isinstance(b, ModelMeta) for b in bases):
            # the ``Model`` base itself
            cls._fields = {}
            return cls

        fields: dict[str, Field] = {}

        pk = Uuid("ID")
        pk.bind(cls, "id")
        pk.readonly = True
        pk.system = True
        fields["id"] = pk

        declared = [
            (key, value)
            for key, value in ns.items()
            if isinstance(value, Field)
        ]
        declared.sort(key=lambda kv: kv[1]._order)
        for key, field in declared:
            field.bind(cls, key)
            fields[key] = field

        # The order stamp -- hybrid logical clock, see model/hlc.py.
        stamp = String("Order stamp")
        stamp.bind(cls, "hlc")
        stamp.readonly = True
        stamp.system = True
        fields["hlc"] = stamp

        for auto in ("created_at", "updated_at"):
            f = Datetime("Created" if auto == "created_at" else "Updated")
            f.bind(cls, auto)
            f.readonly = True
            f.system = True
            fields[auto] = f

        cls._fields = fields
        cls._actions = _actions_of(ns)
        for действие in cls._actions:
            действие.__set_name__(cls, действие.entry)
        cls._table = ns.get("_table") or table_name(name)
        cls._label = ns.get("_label") or name
        MODEL_REGISTRY[name] = cls
        return cls

    # ``TodoLine.completed`` -> the Field, so expressions work off the class.
    def __getattr__(cls, item):
        fields = cls.__dict__.get("_fields") or {}
        if item in fields:
            return fields[item]
        raise AttributeError(
            f"Model {cls.__name__!r} has no field {item!r}."
            + did_you_mean(item, fields)
        )

    def __repr__(cls):
        return f"<Model {cls.__name__}>"

class RecordSet:
    def __init__(self, model, domain=None):
        self.model = model
        self.domain = domain

    def delete(self, confirm=True, swipe=False):
        from ..ui.nodes import DeleteAction

        return DeleteAction(self.model, domain=self.domain, confirm=confirm,
                            swipe=swipe)

    def __repr__(self):
        return f"<{self.model.__name__}.search({self.domain!r})>"

class Model(metaclass=ModelMeta):
    _fields: dict[str, Field] = {}
    _table = ""

    @classmethod
    def field(cls, name: str) -> Field:
        try:
            return cls._fields[name]
        except KeyError:
            raise DslError(
                f"Unknown field {name!r} in model {cls.__name__}."
                + did_you_mean(name, cls._fields)
            ) from None

    @classmethod
    def create(cls, open=None, values=None, draft=False, target="page"):
        """``Note.create(open=Card, draft=True)`` -- завести новую запись."""
        from ..ui.nodes import CreateAction

        return CreateAction(cls, open=open, values=values, draft=draft,
                            target=target)

    @classmethod
    def search(cls, domain=None):
        """``Note.search(record.done)`` -- набор записей по условию."""
        return RecordSet(cls, domain)

    @classmethod
    def stored_fields(cls):
        return [f for n, f in cls._fields.items() if n != "id" and f.stored]

    @classmethod
    def virtual_fields(cls):
        """Fields backed by a query rather than a column (One2many/Many2many)."""
        return [f for f in cls._fields.values() if not f.stored]

    @classmethod
    def display_field(cls):
        if "name" in cls._fields:
            return cls._fields["name"]
        for f in cls._fields.values():
            if f.ftype == "string" and not f.system:
                return f
        return None

    @classmethod
    def relations(cls):
        return [f for f in cls._fields.values() if isinstance(f, Many2one)]

    #: ``Model.all()`` и ``Model.get()`` читали через живой питоновский
    #: рантайм.
    @classmethod
    def display_name(cls, row: dict) -> str:
        df = cls.display_field()
        if df is None:
            return f"{cls.__name__} #{row.get('id')}"
        return row.get(df.name) or f"#{row.get('id')}"
