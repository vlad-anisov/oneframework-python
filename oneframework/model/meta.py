"""``Model`` -- declarative persisted entity.

Every model automatically gains ``id``, ``created_at`` and ``updated_at``; the
user never declares them but may reference them (``created_at.desc()``).
"""

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
    """Уже объявленное действие -- то, что вернул ``action(...)``.

    По утиному признаку, а не импортом: :mod:`oneframework.device` тянет за собой
    пути и файлы, а метакласс модели исполняется при каждом импорте модели.
    """
    return hasattr(value, "declaration") and hasattr(value, "writes")


def _actions_of(ns):
    """Действия модели -- её же методы.

    Помечать их нечем и незачем. Метод модели -- это поведение записи, а
    другого поведения у неё не бывает: считает его устройство, потому что
    другого исполнителя нет. Декоратор сообщал бы единственно возможное.

    Не действия только два рода имён, и оба узнаются по правилам самого
    питона, а не по нашим:

    * начинающиеся с ``_`` -- в питоне это и значит «не наружу». Вычисляемые
      поля пишутся ими (``compute=_progress``), и вызывать их кнопкой
      незачем: их зовёт поле;
    * ``staticmethod``, ``classmethod`` и ``property`` -- у них нет набора
      записей первым доводом, а действие только им и работает.

    Уточнить всё же можно -- ``@action(writes=[details])``, -- если хочется
    сузить список полей или подписать действие иначе. Это качественное
    прилагательное к методу, а не разрешение быть методом.
    """
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

        # Auto primary key. A UUID rather than a counter: two devices working
        # offline both hand out row 4, and when their data meets there is
        # nothing left to tell those two records apart -- see model/ids.py.
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

        # The order stamp -- hybrid logical clock, see model/hlc.py. "Last one
        # wins" needs a "last", and neither the changeset nor the wall clock
        # provides one that every device agrees on.
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
        # Логика, объявленная методами. Собирается здесь по той же причине, по
        # которой здесь собираются поля: и то и другое -- части модели, и
        # спрашивать о них надо у неё, а не у приложения.
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
    """Набор записей, названный условием. Пока -- объявление, не данные.

    Существует ради одного: чтобы удаление множества писалось тем же словом,
    что удаление одной записи. ``Note.search(...).delete()`` и
    ``record.delete()`` -- один метод, разные наборы.
    """

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
    """Base class for persisted entities."""

    _fields: dict[str, Field] = {}
    _table = ""

    # -- introspection helpers -------------------------------------------
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
        """``Note.create(open=Card, draft=True)`` -- завести новую запись.

        Метод модели, а не отдельное действие: заводит записи модель, у
        отдельной записи для этого нет ни имени, ни места. Ровно то же
        разделение, что у ``unlink`` и ``create`` в Odoo.
        """
        from ..ui.nodes import CreateAction

        return CreateAction(cls, open=open, values=values, draft=draft,
                            target=target)

    @classmethod
    def search(cls, domain=None):
        """``Note.search(record.done)`` -- набор записей по условию.

        Возвращает не записи, а **объявление набора**: приложение объявляют,
        а не исполняют, и читать базу здесь нечем и незачем. У набора есть то
        же, что у записи: ``.delete()``. Так «удалить всё выполненное»
        пишется тем же методом, что «удалить эту» -- ``Note.search(...)``
        просто говорит, каких именно.
        """
        return RecordSet(cls, domain)

    @classmethod
    def stored_fields(cls):
        """Fields that map to a column, primary key excluded."""
        return [f for n, f in cls._fields.items() if n != "id" and f.stored]

    @classmethod
    def virtual_fields(cls):
        """Fields backed by a query rather than a column (One2many/Many2many)."""
        return [f for f in cls._fields.values() if not f.stored]

    @classmethod
    def display_field(cls):
        """Field used as the human label of a record.

        ``name`` when present, else the first ``String``, else ``None``.
        """
        if "name" in cls._fields:
            return cls._fields["name"]
        for f in cls._fields.values():
            if f.ftype == "string" and not f.system:
                return f
        return None

    @classmethod
    def relations(cls):
        """Stored relations, i.e. the ones that own a foreign key column."""
        return [f for f in cls._fields.values() if isinstance(f, Many2one)]

    #: ``Model.all()`` и ``Model.get()`` читали через живой питоновский
    #: рантайм. Его нет: виды едут документами, ``ui`` на устройстве не
    #: исполняется. Цикл по записям пишется ``Repeat(Board, Tab(...))``.
    @classmethod
    def display_name(cls, row: dict) -> str:
        df = cls.display_field()
        if df is None:
            return f"{cls.__name__} #{row.get('id')}"
        return row.get(df.name) or f"#{row.get('id')}"
