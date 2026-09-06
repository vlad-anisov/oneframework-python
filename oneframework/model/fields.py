"""Field types."""

from __future__ import annotations

import datetime as _dt

import json

from ..errors import DslError, did_you_mean
from .expr import Ref
from .ids import new_id

__all__ = [
    "Field", "register_widget",
    "String", "Uuid", "Integer", "Float", "Monetary", "Duration",
    "Boolean", "Selection", "Color", "Json",
    "Date", "Datetime", "Time",
    "Binary", "GeoPoint",
    "Many2one", "One2one", "One2many", "Many2many",
]

MODEL_REGISTRY: dict[str, type] = {}

def register_widget(field_type, name):
    if not (isinstance(field_type, type) and issubclass(field_type, Field)):
        raise DslError(f"register_widget expects a Field subclass, got {field_type!r}.")
    if name not in field_type.widgets:
        field_type.widgets = (*field_type.widgets, name)
    return name

class Field(Ref):
    ftype = "string"
    sql_type = "TEXT"
    #: widget used when the user writes ``text()`` with no override
    default_widget = "text"
    widgets = ("text",)
    py_default = None
    #: does this field own a column? One2many/Many2many do not.
    stored = True
    #: kept by the framework, not by the app: ``id``, ``hlc``, ``created_at``,
    #: ``updated_at``.
    system = False

    def __init_subclass__(cls, **прочее):
        super().__init_subclass__(**прочее)
        # Свой `ftype` объявляют не все: `Text` -- это `String` с другими
        # умолчаниями, и таблицу он берёт у родителя.
        свой = cls.__dict__.get("ftype")
        if свой is None:
            return
        from ..protocol import load

        описание = load()["types"].get(свой)
        if описание is None:
            raise DslError(
                f"{cls.__name__}: типа поля «{свой}» нет в protocol/field-types.json. "
                "Тип объявляется там -- один раз на все языки; класс здесь только "
                "называет его по имени."
            )
        cls.sql_type = описание["sql"]
        cls.default_widget = описание["widget"]
        cls.widgets = tuple(описание["widgets"])
        cls.stored = bool(описание["stored"])

    __hash__ = object.__hash__

    _counter = 0

    def __init__(self, label=None, required=False, default=None, help=None,
                 compute=None):
        self.label = label
        self.required = required
        self.help = help
        self._explicit_default = default
        self.name = None
        self.owner = None
        self.compute = None
        if compute is not None:
            # Выражением -- `compute=expr("count(Task, via=board)")`.
            self.computed_by(compute)
        Field._counter += 1
        self._order = Field._counter

    def computed_by(self, formula, name=None):  # noqa: D401
        """Поле считается формулой, а не хранится."""
        if callable(formula):
            raise DslError(
                "Формула пишется выражением, а не питоновской функцией: "
                'compute=expr("count(Task, via=board)"). Питоновскую формулу '
                "приходилось исполнять с подставными объектами, чтобы получить "
                "дерево, -- и умел это один язык из трёх.")
        self.compute = formula
        self.stored = False
        self.readonly = True
        return self

    # -- ownership ---------------------------------------------------------
    def __set_name__(self, owner, name):
        # Only the first binding wins: a field object belongs to one class.
        if self.name is None:
            self.name = name
            self.owner = owner

    def bind(self, owner, name):
        self.name = name
        self.owner = owner
        return self

    def __deepcopy__(self, memo):
        return self

    @property
    def ref_name(self):
        return self.name

    @property
    def column(self):
        """Physical column name (``Many2one`` overrides this)."""
        return self.name

    @property
    def display_label(self):
        return self.label or (self.name or "").replace("_", " ").capitalize()

    # -- UI factory --------------------------------------------------------
    def __call__(self, widget=None, label=None, **options):
        from ..ui.nodes import FieldNode

        if widget is not None and widget not in self.widgets:
            raise DslError(
                f"Unknown widget {widget!r} for {type(self).__name__} field "
                f"{self.name or '<unnamed>'!r}."
                + did_you_mean(widget, self.widgets)
                + f" Available: {', '.join(sorted(self.widgets))}."
            )
        return FieldNode(self, widget=widget, label=label, **options)

    # -- values ------------------------------------------------------------
    def default(self):
        if self._explicit_default is not None:
            return self._explicit_default
        return self.py_default

    def to_db(self, value):
        return value

    def from_db(self, value):
        return value

    def to_json(self, value):
        return value

    def __repr__(self):
        owner = getattr(self.owner, "__name__", None)
        return f"{type(self).__name__}({owner}.{self.name})"

class String(Field):
    ftype = "string"

    #: What the value *means*, which is what both platforms call it: the same
    #: idea as `UITextContentType` on iOS and `autofillHints` on Android.
    SEMANTICS = ("text", "email", "phone", "url", "password", "barcode", "rich")

    def __init__(self, label=None, lines=1, semantic="text", **kw):
        if semantic not in self.SEMANTICS:
            raise DslError(
                f"String(semantic={semantic!r}) is not valid."
                + did_you_mean(semantic, self.SEMANTICS)
                + f" Valid: {', '.join(self.SEMANTICS)}."
            )
        super().__init__(label=label, **kw)
        self.lines = lines
        self.semantic = semantic
        if semantic != "text":
            self.default_widget = semantic
        elif lines > 1:
            self.default_widget = "textarea"

    def to_db(self, value):
        return None if value is None else str(value)

class Boolean(Field):
    ftype = "boolean"
    py_default = False

    def to_db(self, value):
        return 1 if value else 0

    def from_db(self, value):
        return bool(value)

    def to_json(self, value):
        return bool(value)

class Integer(Field):
    ftype = "integer"
    py_default = 0

    def __init__(self, label=None, maximum=None, **kw):
        """``maximum`` bounds a score or a count -- what `Rating` used to be."""
        super().__init__(label=label, **kw)
        self.maximum = maximum

    def to_db(self, value):
        return 0 if value is None else int(value)

    def from_db(self, value):
        return 0 if value is None else int(value)

class Color(Field):
    ftype = "color"

    def to_db(self, value):
        if value is None:
            return None
        value = str(value).strip()
        if not value:
            return None
        return value

class Datetime(Field):
    """ISO-8601 UTC timestamp, stored as TEXT so it sorts lexicographically."""
    ftype = "datetime"

    @staticmethod
    def now():
        # Microsecond precision: millisecond stamps tie for records created in
        # the same loop iteration, which makes "newest first" look arbitrary.
        return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    def to_db(self, value):
        if isinstance(value, _dt.datetime):
            return value.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        return value

class Date(Field):
    """Calendar date, stored as ISO ``YYYY-MM-DD``."""
    ftype = "date"

    def to_db(self, value):
        if isinstance(value, _dt.datetime):
            return value.date().isoformat()
        if isinstance(value, _dt.date):
            return value.isoformat()
        if value in (None, ""):
            return None
        return str(value)[:10]

class Many2one(Field):
    """Reference to another :class:`~oneframework.model.meta.Model`."""
    ftype = "many2one"

    def __init__(self, comodel, label=None, required=False, default=None, help=None,
                 unique=False,
                 ondelete="set null"):
        super().__init__(label=label, required=required, default=default, help=help)
        self.comodel = comodel
        #: A one-to-one is a many-to-one that may not repeat -- a constraint,
        #: not a type.
        self.unique = unique
        if unique and ondelete == "set null":
            ondelete = "cascade"
        self.ondelete = ondelete

    @property
    def column(self):
        return f"{self.name}_id"

    def resolve_comodel(self):
        if isinstance(self.comodel, str):
            try:
                return MODEL_REGISTRY[self.comodel]
            except KeyError:
                raise DslError(
                    f"Many2one on {getattr(self.owner, '__name__', '?')}.{self.name} "
                    f"points at unknown model {self.comodel!r}."
                    + did_you_mean(self.comodel, MODEL_REGISTRY)
                ) from None
        return self.comodel

    def to_db(self, value):
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get("id")
        elif hasattr(value, "id"):
            value = value.id
        if value is None or value == "":
            return None
        return str(value)

# --- numeric -----------------------------------------------------------------
class Float(Field):
    """Real number. ``digits`` is (precision, scale) as in Odoo."""
    ftype = "float"
    py_default = 0.0

    def __init__(self, label=None, digits=(16, 2), unit=None, **kw):
        super().__init__(label=label, **kw)
        self.digits = digits
        self.unit = unit
        if unit:
            self.default_widget = "unit"

    def to_db(self, value):
        if value in (None, ""):
            return 0.0
        return round(float(value), self.digits[1] if self.digits else 6)

    def from_db(self, value):
        return 0.0 if value is None else float(value)

class Monetary(Float):
    ftype = "monetary"

    def to_db(self, value):
        if value is None:
            return None
        return round(float(value) * (10 ** self.digits[1]))

    def from_db(self, value):
        if value is None:
            return self.py_default
        return int(value) / (10 ** self.digits[1])

    def __init__(self, label=None, currency="USD", **kw):
        super().__init__(label=label, **kw)
        self.currency = currency

class Duration(Integer):
    ftype = "duration"

# --- text variants -- separate types because the platform keyboard differs ---
class Uuid(String):
    ftype = "uuid"

    def default(self):
        value = super().default()
        return value if value else new_id()

class Json(Field):
    ftype = "json"

    def to_db(self, value):
        # ``sort_keys=True`` -- решение, а не украшение.
        return None if value is None else json.dumps(value, ensure_ascii=False,
                                                     sort_keys=True)

    def from_db(self, value):
        if value in (None, ""):
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None

class Selection(Field):
    ftype = "selection"

    def __init__(self, selection, label=None, **kw):
        super().__init__(label=label, **kw)
        self.selection = [
            (v, v.replace("_", " ").capitalize()) if isinstance(v, str) else tuple(v)
            for v in selection
        ]

    @property
    def choices(self):
        return [{"value": v, "label": lbl} for v, lbl in self.selection]

    def to_db(self, value):
        return None if value in (None, "") else str(value)

class Time(Field):
    """Clock time, stored as ISO ``HH:MM``."""
    ftype = "time"

    def to_db(self, value):
        if isinstance(value, _dt.time):
            return value.strftime("%H:%M")
        if isinstance(value, _dt.datetime):
            return value.strftime("%H:%M")
        return None if value in (None, "") else str(value)[:5]

# --- binary ------------------------------------------------------------------
class Binary(Field):
    ftype = "binary"

    def __init__(self, label=None, accept=None, max_size=5_000_000, **kw):
        """``accept`` is the file dialog's filter -- and what made `Image` a separate type."""
        super().__init__(label=label, **kw)
        self.accept = accept
        self.max_size = max_size
        if accept and accept.startswith("image/"):
            self.default_widget = "image"

    def to_db(self, value):
        return None if value in (None, "") else str(value)

class GeoPoint(Field):
    """A latitude/longitude pair, stored as ``"lat,lon"``."""
    ftype = "geopoint"

    def to_db(self, value):
        if value in (None, ""):
            return None
        if isinstance(value, (tuple, list)) and len(value) == 2:
            return f"{float(value[0]):.6f},{float(value[1]):.6f}"
        return str(value)

    def from_db(self, value):
        if not value:
            return None
        try:
            lat, lon = str(value).split(",")
            return [float(lat), float(lon)]
        except (ValueError, TypeError):
            return None

class One2one(Many2one):
    ftype = "one2one"

    def __init__(self, comodel, label=None, ondelete="cascade", **kw):
        super().__init__(comodel, label=label, unique=True, ondelete=ondelete, **kw)

class One2many(Field):
    """The many side of a ``Many2one``, addressed from the parent."""
    ftype = "one2many"

    def __init__(self, comodel, inverse, label=None, **kw):
        super().__init__(label=label, **kw)
        self.comodel = comodel
        self.inverse = inverse

    @property
    def column(self):
        return None

    def resolve_comodel(self):
        if isinstance(self.comodel, str):
            try:
                return MODEL_REGISTRY[self.comodel]
            except KeyError:
                raise DslError(
                    f"One2many on {getattr(self.owner, '__name__', '?')}.{self.name} "
                    f"points at unknown model {self.comodel!r}."
                    + did_you_mean(self.comodel, MODEL_REGISTRY)
                ) from None
        return self.comodel

    def inverse_field(self):
        """The ``Many2one`` on the comodel that this field is the inverse of."""
        co = self.resolve_comodel()
        field = co._fields.get(self.inverse)
        if field is None or not isinstance(field, Many2one):
            raise DslError(
                f"One2many {getattr(self.owner, '__name__', '?')}.{self.name} needs "
                f"'{self.inverse}' to be a Many2one on {co.__name__}."
                + did_you_mean(
                    self.inverse,
                    [n for n, f in co._fields.items() if isinstance(f, Many2one)],
                )
            )
        return field

class Many2many(Field):
    ftype = "many2many"

    def __init__(self, comodel, label=None, relation=None, **kw):
        super().__init__(label=label, **kw)
        self.comodel = comodel
        self._relation = relation

    @property
    def column(self):
        return None

    def resolve_comodel(self):
        if isinstance(self.comodel, str):
            try:
                return MODEL_REGISTRY[self.comodel]
            except KeyError:
                raise DslError(
                    f"Many2many on {getattr(self.owner, '__name__', '?')}.{self.name} "
                    f"points at unknown model {self.comodel!r}."
                    + did_you_mean(self.comodel, MODEL_REGISTRY)
                ) from None
        return self.comodel

    def relation(self):
        """``(table, own_column, other_column)`` for the join table."""
        own = self.owner._table
        other = self.resolve_comodel()._table
        table = self._relation or f"{own}_{other}_{self.name}_rel"
        return table, f"{own}_id", f"{other}_id"

FIELD_TYPES = {
    "string": String,
    "uuid": Uuid,
    "integer": Integer,
    "float": Float,
    "monetary": Monetary,
    "duration": Duration,
    "boolean": Boolean,
    "json": Json,
    "selection": Selection,
    "color": Color,
    "date": Date,
    "datetime": Datetime,
    "time": Time,
    "binary": Binary,
    "geopoint": GeoPoint,
    "many2one": Many2one,
    "one2one": One2one,
    "one2many": One2many,
    "many2many": Many2many,
}

# --------------------------------------------------------------------------
# shorthands
# --------------------------------------------------------------------------
# Not types -- functions that spell a common property combination.

def Text(label=None, lines=4, **kw):
    """Multi-line string -- `lineLimit` on iOS, `maxLines` on Android."""
    return String(label, lines=lines, **kw)

def Html(label=None, lines=6, **kw):
    return String(label, lines=lines, semantic="rich", **kw)

def Email(label=None, **kw):
    return String(label, semantic="email", **kw)

def Phone(label=None, **kw):
    return String(label, semantic="phone", **kw)

def Url(label=None, **kw):
    return String(label, semantic="url", **kw)

def Password(label=None, **kw):
    return String(label, semantic="password", **kw)

def Barcode(label=None, **kw):
    return String(label, semantic="barcode", **kw)

def Percent(label=None, digits=(5, 2), **kw):
    return Float(label, digits=digits, unit="%", **kw)

def Rating(label=None, maximum=5, **kw):
    return Integer(label, maximum=maximum, **kw)

def Image(label=None, accept="image/*", **kw):
    return Binary(label, accept=accept, **kw)

Signature = Image

SHORTHANDS = (
    "Text", "Html", "Email", "Phone", "Url", "Password", "Barcode",
    "Percent", "Rating", "Image", "Signature",
)
__all__ += list(SHORTHANDS)
