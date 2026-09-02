"""Field types.

A ``Field`` plays three roles at once, which is central to the DSL:

* **metadata**   -- label, sql type, widget capabilities
* **reference**  -- ``completed == False`` builds a domain (via :class:`Ref`)
* **UI factory** -- ``completed(widget="toggle")`` builds a :class:`FieldNode`

Fields are declared on ``Model`` (persisted, becomes a column) or on ``View``
(transient state, never touches the schema). The class that owns them decides;
the field itself is agnostic.
"""

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
    """Teach a field type a widget shipped by a module.

    A module's ``static/widgets.js`` is only half of a custom widget: the DSL
    checks ``widget="..."`` against the field's own list, so without this the
    name is rejected before the renderer ever sees it. Both halves use the same
    ``<ftype>:<name>`` key.

        register_widget(Boolean, "star")     # -> boolean:star

    Idempotent, so a module re-imported by a second app adds nothing twice.
    """
    if not (isinstance(field_type, type) and issubclass(field_type, Field)):
        raise DslError(f"register_widget expects a Field subclass, got {field_type!r}.")
    if name not in field_type.widgets:
        field_type.widgets = (*field_type.widgets, name)
    return name


class Field(Ref):
    """Base field. Подкласс называет свой ``ftype``; остальное берётся из таблицы.

    Колонка, виджеты и умолчания **не пишутся здесь**. Они лежат в
    ``protocol/field-types.json`` -- том же файле, который читают привязки на
    JavaScript и Kotlin, -- и подтягиваются в класс при его объявлении. Опиши
    их питон своими классами, завести тип поля можно было бы только его
    правкой, а два других языка остались бы читателями чужого договора.
    """

    #: semantic type exposed to the renderer
    ftype = "string"
    #: sqlite column affinity
    sql_type = "TEXT"
    #: widget used when the user writes ``text()`` with no override
    default_widget = "text"
    #: widgets this field type accepts
    widgets = ("text",)
    #: value used when a record is created without this field
    py_default = None
    #: does this field own a column? One2many/Many2many do not.
    stored = True
    #: kept by the framework, not by the app: ``id``, ``hlc``, ``created_at``,
    #: ``updated_at``. Nobody writes them through the API, and code that asks
    #: "did the user fill anything in" has to skip them -- an order stamp is a
    #: string like any other, and counting it as content would mean no record
    #: is ever empty.
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
        #: Имя объявленного действия, которое считает это поле. Колонки у такого
        #: поля нет намеренно: значение, положенное в колонку, стареет молча --
        #: подзадачу завершили, а готовность списка осталась вчерашней. Здесь
        #: значение спрашивается тогда, когда его рисуют, и потому не врёт.
        self._compute = None
        self._formula_fn = None
        if compute is not None:
            # Функцию передают саму собой -- `compute=_progress`. Ни декоратора,
            # ни имени строкой: опечатку в строке нашёл бы рантайм, а тут её не
            # бывает, и переход по имени работает как у обычной функции.
            self.computed_by(compute)
        Field._counter += 1
        self._order = Field._counter

    @property
    def compute(self):
        """Формула деревом. Прогоняется один раз, когда её впервые спросят."""
        if self._compute is None and self._formula_fn is not None:
            from .expr import trace_formula

            self._compute = trace_formula(self._formula_fn, model=self.owner)
        return self._compute

    @compute.setter
    def compute(self, value):
        self._compute = value

    def computed_by(self, formula, name=None):  # noqa: D401
        """Поле считается формулой, а не хранится. Правило -- в одном месте.

        Ставится и из конструктора (``compute=``), и декоратором
        :func:`~oneframework.model.expr.compute`, который вешает формулу уже после
        создания поля. Развести эти два пути значило бы завести два правила о
        том, что такое вычисляемое поле, и однажды они разойдутся.
        """
        if callable(formula):
            # Прогон откладывается: в теле класса модели ещё нет, а формуле
            # нужен `self`, знающий свои связи -- чтобы `self.tasks` было
            # набором задач, а не просто именем. Считается один раз, при первом
            # обращении, когда модель уже собрана.
            name = name or getattr(formula, "__name__", None)
            self._formula_fn = formula
            formula = None
        self.compute = formula
        self.compute_name = name
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
        """Explicitly attach this field (used by the View metaclass)."""
        self.name = name
        self.owner = owner
        return self

    def __deepcopy__(self, memo):
        """A field is a definition, and there is one of each.

        Copying a subtree of the UI -- what expanding a repeat does -- must not
        copy the fields it points at: two ``Task.title`` objects would compare
        unequal, and the code that asks "is this the list's handle field" would
        start answering no.
        """
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
        """Value as handed to the JS renderer."""
        return value

    def __repr__(self):
        owner = getattr(self.owner, "__name__", None)
        return f"{type(self).__name__}({owner}.{self.name})"


class String(Field):
    ftype = "string"

    #: What the value *means*, which is what both platforms call it: the same
    #: idea as `UITextContentType` on iOS and `autofillHints` on Android. It
    #: picks the keyboard, the autofill hint and the default control -- none of
    #: which is a reason for a separate type.
    SEMANTICS = ("text", "email", "phone", "url", "password", "barcode", "rich")

    def __init__(self, label=None, lines=1, semantic="text", **kw):
        """One string type, as on both platforms.

        How many lines it shows is a property of the field, not a second column
        type -- `lineLimit` on iOS, `maxLines` on Android.
        """
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
    """Reference to another :class:`~oneframework.model.meta.Model`.

    Stored as ``<name>_id INTEGER REFERENCES <table>(id)``.
    """

    ftype = "many2one"

    def __init__(self, comodel, label=None, required=False, default=None, help=None,
                 unique=False,
                 ondelete="set null"):
        super().__init__(label=label, required=required, default=default, help=help)
        self.comodel = comodel
        #: A one-to-one is a many-to-one that may not repeat -- a constraint,
        #: not a type. Owning a counterpart also means taking it along on
        #: delete, which is why the default changes with it.
        self.unique = unique
        if unique and ondelete == "set null":
            ondelete = "cascade"
        self.ondelete = ondelete

    @property
    def column(self):
        return f"{self.name}_id"

    def resolve_comodel(self):
        """Return the comodel class, resolving string forward references."""
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




# --------------------------------------------------------------------------
# numeric
# --------------------------------------------------------------------------
class Float(Field):
    """Real number. ``digits`` is (precision, scale) as in Odoo."""

    ftype = "float"
    py_default = 0.0

    def __init__(self, label=None, digits=(16, 2), unit=None, **kw):
        super().__init__(label=label, **kw)
        self.digits = digits
        #: A suffix shown beside the number -- "%", "kg", "ч". Neither platform
        #: has a percent *type*: it is a formatting style on a number, and so
        #: is every other unit.
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
    """Amount of money, stored as whole minor units.

    A float cannot hold a decimal amount exactly, and the error accumulates
    over a sum -- so the column is an integer count of cents, which is what
    Android's money handling does and what Core Data's `Decimal` achieves.
    The DSL and the UI still see an ordinary amount.

    ``currency`` is an ISO code or a sibling field name.
    """

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
    """A span of time, stored as whole seconds."""

    ftype = "duration"


# --------------------------------------------------------------------------
# text variants -- separate types because the platform keyboard differs
# --------------------------------------------------------------------------
class Uuid(String):
    """An identifier the device makes up on its own.

    A row id is a counter, and two devices working offline hand out the same
    counter -- so the moment their data meets, the ids collide. A UUID is
    generated locally, needs no coordination and never collides, which is what
    makes a record referable across devices. Core Data has the type for the
    same reason.

    Version 7, so the value still sorts by the moment it was made: this is the
    primary key, and ``ORDER BY id`` has to keep meaning "in the order they
    were added". See :mod:`oneframework.model.ids`.
    """

    ftype = "uuid"

    def default(self):
        value = super().default()
        return value if value else new_id()


class Json(Field):
    """Any JSON-serialisable structure -- a dict, a list, a nested mix.

    The escape hatch every persistence layer keeps open: Core Data calls it
    `Transformable`, Room calls it a `TypeConverter`. Without one, a field the
    framework has no type for cannot be stored at all.
    """

    ftype = "json"

    def to_db(self, value):
        # ``sort_keys=True`` -- решение, а не украшение. Порядок ключей теряется
        # на границе модуля: значение приезжает туда текстом, разбирается
        # каноническим разбором, а у канонического вида объект -- это
        # отсортированная карта (``core/src/canon.rs``). Сохранить исходный
        # порядок значило бы завести внутри модуля **второй** разбор, не
        # канонический, -- ровно ту вторую реализацию, ради отсутствия которой
        # ядро и выносилось. Поэтому порядок теряется осознанно и одинаково у
        # всех трёх сторон: одно значение -- один текст в колонке, а значит ни
        # одной лишней правки в changeset. Чем платим -- записано тестом
        # ``test_a_json_object_loses_its_key_order_on_purpose``.
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
    """One of a fixed set of values.

    ``Selection([("draft", "Draft"), ("done", "Done")], "State")``
    """

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


# --------------------------------------------------------------------------
# binary
# --------------------------------------------------------------------------
class Binary(Field):
    """A file, stored as a data URI so it travels with the record."""

    ftype = "binary"

    def __init__(self, label=None, accept=None, max_size=5_000_000, **kw):
        """``accept`` is the file dialog's filter -- and what made `Image` a
        separate type. `Binary("Фото", accept="image/*")` says the same thing,
        and picks the picture control by itself."""
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
    """A many-to-one that may not repeat.

    Kept as a type rather than a flag because it says something a constraint
    cannot: this record *owns* its counterpart, which is why deleting one takes
    the other with it. Core Data spells the same thing as a to-one relationship
    with an inverse and a cascade rule.
    """

    ftype = "one2one"

    def __init__(self, comodel, label=None, ondelete="cascade", **kw):
        super().__init__(comodel, label=label, unique=True, ondelete=ondelete, **kw)


class One2many(Field):
    """The many side of a ``Many2one``, addressed from the parent.

    Owns no column: it is a query over the comodel, driven by *inverse* -- the
    name of the ``Many2one`` on the other model that points back here.
    """

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
    """A symmetric many-to-many, materialised as a join table.

    The table name defaults to ``<a>_<b>_rel`` and can be pinned with
    *relation* so two models can share one.
    """

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


#: Every concrete field type, for error messages and introspection.
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
# Not types -- functions that spell a common property combination. Both mobile
# platforms model these as one string (or one number) plus a semantic hint, and
# so does the field they return: `Email("Почта").ftype` is `"string"`. The
# short name is for the person writing the model; the framework below still
# sees the sixteen types it had before.

def Text(label=None, lines=4, **kw):
    """Multi-line string -- `lineLimit` on iOS, `maxLines` on Android."""
    return String(label, lines=lines, **kw)


def Html(label=None, lines=6, **kw):
    """Rich text: the string a formatting editor writes into."""
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
    """A number shown with a suffix -- a formatting style, not a type."""
    return Float(label, digits=digits, unit="%", **kw)


def Rating(label=None, maximum=5, **kw):
    return Integer(label, maximum=maximum, **kw)


def Image(label=None, accept="image/*", **kw):
    """A binary the picker filters to pictures."""
    return Binary(label, accept=accept, **kw)


Signature = Image

SHORTHANDS = (
    "Text", "Html", "Email", "Phone", "Url", "Password", "Barcode",
    "Percent", "Rating", "Image", "Signature",
)
__all__ += list(SHORTHANDS)
