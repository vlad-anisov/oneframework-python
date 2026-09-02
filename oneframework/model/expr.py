"""Expression AST, context proxies and the UNSET sentinel.

Nothing in here touches SQL. Domains built by the DSL are pure trees; the
compiler in :mod:`oneframework.model.query` turns them into parameterised SQL.

The tree distinguishes three kinds of reference:

``Field``           a real model field (defined in :mod:`oneframework.model.fields`)
``RecordFieldRef``  ``record.tag`` -- the row being evaluated; which model that
                    is depends on where the reference sits, so it is resolved
                    late, when the enclosing ``List`` or ``View`` is known
``ViewFieldRef``    ``view.tag``   -- transient state of the enclosing View
"""

from __future__ import annotations

import re

import ast
import inspect
import textwrap

from ..errors import DslError, did_you_mean

__all__ = [
    "UNSET",
    "Arith",
    "RelatedSet",
    "trace_formula",
    "Round",
    "Expr",
    "Ref",
    "RecordFieldRef",
    "ViewFieldRef",
    "ItemFieldRef",
    "Template",
    "parse_template",
    "Cmp",
    "And",
    "Or",
    "Not",
    "IsNull",
    "Aggregate",
    "Count",
    "Exists",
    "Order",
    "record",
    "view",
    "item",
    "map_refs",
    "iter_refs",
]


class _Unset:
    """UI state that the user has not chosen yet.

    Deliberately distinct from ``None``/SQL ``NULL``: a comparison against
    UNSET is *dropped* from the query instead of becoming ``IS NULL``.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "UNSET"

    def __bool__(self):
        return False

    def __reduce__(self):
        return (_Unset, ())


UNSET = _Unset()


class Expr:
    """Base class for boolean domain nodes."""

    def __and__(self, other):
        return And(self, other)

    def __or__(self, other):
        return Or(self, other)

    def __invert__(self):
        return Not(self)

    def __bool__(self):
        raise DslError(
            f"{type(self).__name__} cannot be used as a Python boolean. "
            "Combine domain expressions with '&', '|' and '~' "
            "(e.g. (flag == False) & (rank > 0))."
        )

    def _map_refs(self, fn):  # pragma: no cover - overridden
        raise NotImplementedError


class Ref:
    """Anything that resolves to a column or a value.

    Comparison operators build :class:`Cmp` nodes rather than returning bools,
    which is what makes ``record.completed == False`` a domain instead of
    ``False``.

    A boolean field is already a condition, so ``&``, ``|`` and ``~`` work on
    the reference itself: ``record.starred & ~record.done``. That is how the
    sentence reads in Python, and it is the only spelling a linter accepts --
    ``== False`` is exactly what E712 exists to stop people writing.
    """

    __hash__ = object.__hash__

    def __and__(self, other):
        return And(self, other)

    def __or__(self, other):
        return Or(self, other)

    def __invert__(self):
        return Not(self)

    def __eq__(self, other):
        return Cmp("=", self, other)

    def __ne__(self, other):
        return Cmp("!=", self, other)

    def __lt__(self, other):
        return Cmp("<", self, other)

    def __le__(self, other):
        return Cmp("<=", self, other)

    def __gt__(self, other):
        return Cmp(">", self, other)

    def __ge__(self, other):
        return Cmp(">=", self, other)

    def is_null(self):
        """Explicit SQL ``NULL`` test (never implied by UNSET)."""
        return IsNull(self)

    def asc(self):
        return Order(self, "asc")

    def desc(self):
        return Order(self, "desc")

    @property
    def ref_name(self):  # pragma: no cover - overridden
        raise NotImplementedError


class _NamedRef(Ref):
    """A field named by the scope it belongs to rather than by its class.

    Здесь же стоит запрет на «истинность». Это ссылка в формуле -- ``self.total``,
    ``record.done``, -- и до базы у неё значения нет. Молчание тут было
    настоящей дырой: ``if self.total:`` брал первую ветку **всегда**, потому что
    ссылка -- обычный объект, а объект истинен. Ни ошибки, ни следа: формула
    считала не то, что написано.

    Объект поля (``Field``) сюда не входит намеренно: каркас законно проверяет
    его на существование (``df.name if df else None``), и запрет там сломал бы
    сборку документа.

    Calling one builds the UI node, exactly as calling a :class:`Field` does --
    ``record.title(widget="title")``. The field object itself is found later,
    when the enclosing ``List`` or ``View`` says which model this is about.
    """

    __hash__ = object.__hash__

    def __bool__(self):
        raise DslError(
            f"{self!r} -- это ссылка на поле, а не значение: «истинно ли оно» "
            "станет известно только у базы. Напишите тройное выражение "
            "(a if ... else b) -- оно уедет в запрос ветвлением."
        )

    def __init__(self, name):
        self.name = name

    @property
    def ref_name(self):
        return self.name

    def __call__(self, widget=None, label=None, **options):
        from ..ui.nodes import FieldNode

        return FieldNode(self, widget=widget, label=label, **options)


class _SliceRefused:
    """Срез у ссылки -- тот же отказ, что и у выражения."""

    def __getitem__(self, key):
        raise DslError(
            "срез и обращение по номеру базе не выразить точно: у питона и у "
            "SQL они считают по-разному с конца. Пишите `.startswith(...)`, "
            "`.endswith(...)` или `.replace(...)`."
        )


class RecordFieldRef(_NamedRef, _SliceRefused):
    """``record.tag`` -- a column of the row currently being evaluated.

    Внутри формулы ссылка знает **тип** своего поля: его объявила модель, и
    знать его на сборке дешевле, чем гадать на исполнении. От типа зависит
    смысл питоновских записей -- ``+`` у строк это склейка, а у чисел
    сложение, и SQLite на этом расходится с питоном молча.
    """

    __hash__ = object.__hash__
    ftype = None

    def typed(self, ftype):
        """Та же ссылка, но с объявленным типом."""
        other = RecordFieldRef(self.name)
        other.ftype = ftype
        return other

    def __add__(self, other):
        if self.ftype == "string" or isinstance(other, str):
            return Template([self, other])
        return Arith("+", [self, other])

    def __radd__(self, other):
        if self.ftype == "string" or isinstance(other, str):
            return Template([other, self])
        return Arith("+", [other, self])

    def __getattr__(self, name):
        return _string_method(self, name, f"поля «{self.name}»")

    def __repr__(self):
        return f"record.{self.name}"


def _string_method(owner, name, что):
    """Метод строки у символа -- у ссылки и у выражения одинаково.

    Одинаково это важно: разбор слова любой библиотекой начинается с цепочки
    вроде ``слово.lower().endswith("а")``, и обрывался он раньше на втором
    звене -- ``\'Arith\' object has no attribute\'``, то есть именем нашего
    класса вместо объяснения.
    """
    if name.startswith("_"):
        raise AttributeError(name)
    if name in _STRING_METHODS:
        return lambda *args: _STRING_METHODS[name](owner, *args)
    # ``AttributeError``, а не отказ языка: каркас законно опрашивает узлы
    # через ``getattr(x, "owner", None)``, и отказ здесь ронял бы разбор вида.
    # Объяснение при этом остаётся в тексте.
    raise AttributeError(
        f"у {что} нет метода «{name}»: значение посчитает база, и питоновские "
        "методы строки ей доступны не все."
        + did_you_mean(name, _STRING_METHODS)
    )


#: Слова питона для строк -> операции, которые SQLite умеет **точно**.
#: Чего нет -- отказывает по имени, а не делает похоже: ``upper`` над
#: кириллицей SQLite не умеет вовсе, и молчаливое «АБВ -> абв без изменений»
#: было бы хуже отказа.
_STRING_METHODS = {
    "strip": lambda ref, *a: Arith("trim", [ref, *a]),
    "lstrip": lambda ref, *a: Arith("ltrim", [ref, *a]),
    "rstrip": lambda ref, *a: Arith("rtrim", [ref, *a]),
    "replace": lambda ref, old, new: Arith("replace", [ref, old, new]),
    "startswith": lambda ref, what: Arith("startswith", [ref, what]),
    "endswith": lambda ref, what: Arith("endswith", [ref, what]),
    "lower": lambda ref: Arith("lower", [ref]),
    "upper": lambda ref: Arith("upper", [ref]),
}


class ViewFieldRef(_NamedRef):
    """``view.tag`` -- transient state of the enclosing View."""

    __hash__ = object.__hash__

    def __repr__(self):
        return f"view.{self.name}"


class ItemFieldRef(_NamedRef):
    """``item.name`` -- the record the enclosing ``Repeat`` is drawing.

    The third scope, and the one that lets a view stop being a Python loop: a
    tab per board used to be ``for board in Board.all()``, which bakes the
    boards that existed when the tree was built. ``item`` names the current one
    instead, so the same document draws whatever boards the data holds.

    It is distinct from ``record`` because both can be in scope at once -- a
    List inside a Repeat filters ``record.board == item.id``, where ``record``
    is the task being tested and ``item`` is the board owning the tab.
    """

    __hash__ = object.__hash__

    def __repr__(self):
        return f"item.{self.name}"


class _RecordProxy:
    """Запись, которую сейчас рисуют.

    Приезжает доводом в ``ui(self, record)`` и знает свою модель -- отсюда две
    вещи, которых без модели не было:

    * ``record.summary()`` -- **метод** модели становится действием кнопки
      прямо здесь, потому что видно, что ``summary`` -- не поле;
    * опечатка в имени поля отказывает сразу, с подсказкой, а не превращается
      в ссылку, которая позже разрешится в пустоту.

    Без модели (вид её не объявил) остаётся прежнее поведение: любое имя --
    ссылка. Так пишутся домены списков, где имена принадлежат модели списка, а
    не вида.
    """

    def __init__(self, model=None, origin=None):
        object.__setattr__(self, "_model", model)
        #: Кто спрашивает -- имя вида. Стоит в отказе: без него сообщение
        #: называет модель, но не место, а искать опечатку надо в виде.
        object.__setattr__(self, "_origin", origin)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        model = object.__getattribute__(self, "_model")
        # То, что запись умеет сама. Проверяется раньше полей, в том числе
        # когда модели нет: колонки списка внутри вида без модели принадлежат
        # модели списка, и `record.delete()` там законен.
        #
        # Не молча: поле с таким именем -- столкновение, и о нём надо сказать,
        # а не тихо предпочесть одно другому. Сказать можно только там, где
        # модель известна.
        if name in _RECORD_METHODS:
            if model is not None and name in model._fields:
                from ..errors import DslError

                raise DslError(
                    f"у модели {model.__name__} есть поле «{name}», и оно "
                    f"закрывает собой одноимённый метод записи. Переименуйте "
                    f"поле -- иначе `record.{name}` значит то одно, то другое."
                )
            return _RECORD_METHODS[name]()
        if model is None:
            return RecordFieldRef(name)
        for action in getattr(model, "_actions", ()):
            if action.entry == name:
                return _BoundAction(action)
        if name in model._fields:
            return RecordFieldRef(name)
        from ..errors import DslError, did_you_mean

        известно = list(model._fields) + [a.entry for a in getattr(model, "_actions", ())]
        origin = object.__getattribute__(self, "_origin")
        где = f"{origin}: " if origin else ""
        raise DslError(
            f"{где}record.{name}: у модели {model.__name__} нет ни поля, ни "
            f"метода с таким именем." + did_you_mean(name, известно)
        )

    def __repr__(self):
        model = object.__getattribute__(self, "_model")
        return "record" if model is None else f"record<{model.__name__}>"


def _record_delete():
    """``record.delete()`` -- убрать эту запись из базы.

    Метод записи, а не отдельное действие рядом с ней: удаление -- это то,
    что с записью делают, ровно как ``unlink`` в Odoo. Захотелось удалить
    много -- находят много и зовут то же самое: ``Note.search(...).delete()``.
    """
    def delete(confirm=True, swipe=False):
        from ..ui.nodes import DeleteAction

        return DeleteAction(confirm=confirm, swipe=swipe)
    return delete


def _record_save():
    """``record.save()`` -- записать черновик."""
    def save():
        from ..ui.nodes import SaveAction

        return SaveAction()
    return save


def _record_open():
    """``record.open(Card)`` -- показать эту запись названным видом."""
    def open_(view, target="page"):
        from ..ui.nodes import OpenAction

        return OpenAction(view, None, target=target)
    return open_


#: Что запись умеет помимо своих полей.
_RECORD_METHODS = {
    "delete": _record_delete,
    "save": _record_save,
    "open": _record_open,
}


class _BoundAction:
    """Метод модели, позванный на рисуемой записи: ``record.summary()``.

    Скобки здесь значат «на этой записи», а не «прямо сейчас»: кнопка везёт
    объявление, а зовут его при нажатии. Тот же метод без записи --
    ``Note.summary`` -- значит то же действие, но цель ему выберет тот, кто
    нажмёт.
    """

    def __init__(self, action):
        self.action = action

    def __call__(self, **kw):
        from ..ui.nodes import LogicAction

        return LogicAction(self.action, **kw)

    def __repr__(self):
        return f"<record.{self.action.entry}>"


class _ViewProxy:
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return ViewFieldRef(name)

    def __repr__(self):
        return "view"


class _ItemProxy:
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return ItemFieldRef(name)

    def __repr__(self):
        return "item"


record = _RecordProxy()
view = _ViewProxy()
item = _ItemProxy()



class Arith:
    """Арифметика: то, чего в выражениях не было и из-за чего формулы писались
    деревом руками.

    Отдельный класс, а не :class:`Expr`, потому что арифметика -- это
    **число**, а не условие. ``done * 100`` нельзя поставить в ``visible=``, и
    попытка это сделать обязана отказать словами, а не посчитать истинность
    молча.

    Деление особое. У SQLite ``1/0`` -- это ``NULL``, и принять чужую
    случайность своим правилом нельзя: ветка на ноль **объявляется**, иначе
    компилятор отказывается переводить выражение. Отсюда ``.on_zero(0)``.
    """

    __slots__ = ("op", "args", "zero")

    def __init__(self, op, args, zero=None):
        self.op = op
        self.args = list(args)
        self.zero = zero

    def __add__(self, other):
        return Arith("+", [self, other])

    def __radd__(self, other):
        return Arith("+", [other, self])

    def __sub__(self, other):
        return Arith("-", [self, other])

    def __rsub__(self, other):
        return Arith("-", [other, self])

    def __mul__(self, other):
        return Arith("*", [self, other])

    def __rmul__(self, other):
        return Arith("*", [other, self])

    def __truediv__(self, other):
        return Arith("/", [self, other])

    def __rtruediv__(self, other):
        return Arith("/", [other, self])

    def __round__(self, digits=None):
        """``round(x)`` -- обычная питоновская запись, а не своё имя.

        Знаков после запятой пока нет: поле у нас целое, и притворяться, что
        умеем, хуже, чем отказать.
        """
        if digits:
            # ``round(x, 2)`` -- то же округление, только над сдвинутым числом.
            # Сдвиг и обратный сдвиг пишутся явно: своего слова тут не нужно.
            сдвиг = 10 ** digits
            return Arith("/", [Round(Arith("*", [self, сдвиг])), сдвиг])
        return Round(self)

    def _map_refs(self, fn):
        return Arith(self.op, [_map(a, fn) for a in self.args], self.zero)

    def __getattr__(self, name):
        return _string_method(self, name, "выражения")

    def __getitem__(self, key):
        raise DslError(
            "срез и обращение по номеру базе не выразить точно: у питона и у "
            "SQL они считают по-разному с конца. Пишите `.startswith(...)`, "
            "`.endswith(...)` или `.replace(...)`."
        )

    def __bool__(self):
        raise DslError(
            "значение здесь ещё не посчитано -- его посчитает база, а «да или "
            "нет» нужно прямо сейчас.\n"
            "Если это `if` в теле формулы -- он записывается, а не "
            "выполняется, и такой ошибки не бывает. А вот обычная функция "
            "питона, позванная из формулы, **не разбирается**: её `if` "
            "выполняется сразу. Перенесите её в метод модели -- `self._имя()` "
            "разбирается тем же прогоном, что и сама формула.\n"
            "Если же это число вне формулы -- сравните его: `(record.ранг * 2) > 10`."
        )

    def __repr__(self):
        return "(" + f" {self.op} ".join(repr(a) for a in self.args) + ")"


class Round(Arith):
    """Округление к ближайшему.

    Заведено ради того, чтобы не писать ``(a * 100 + b / 2) / b`` -- запись,
    которая верна, но не читается и молча зависит от целочисленного деления.
    """

    def __init__(self, value):
        super().__init__("round", [value])

    def _map_refs(self, fn):
        return Round(_map(self.args[0], fn))

    def __repr__(self):
        return f"Round({self.args[0]!r})"


#: Арифметику понимают и ссылки, и агрегаты: ``Count(...) * 100`` -- число.
def _more_arith_ops(cls):
    """Остальная арифметика питона. Отдельно от :func:`_arith_ops`, потому что
    ``Arith`` четыре первых операции объявляет сам и своё ``__round__`` терять
    не должен."""
    cls.__mod__ = lambda self, other: Arith("%", [self, other])
    cls.__rmod__ = lambda self, other: Arith("%", [other, self])
    cls.__floordiv__ = lambda self, other: Arith("//", [self, other])
    cls.__rfloordiv__ = lambda self, other: Arith("//", [other, self])
    cls.__pow__ = lambda self, other: Arith("**", [self, other])
    cls.__rpow__ = lambda self, other: Arith("**", [other, self])
    cls.__neg__ = lambda self: Arith("neg", [self])
    cls.__pos__ = lambda self: self
    cls.__abs__ = lambda self: Arith("abs", [self])
    return cls


def _arith_ops(cls):
    cls.__add__ = lambda self, other: Arith("+", [self, other])
    cls.__radd__ = lambda self, other: Arith("+", [other, self])
    cls.__sub__ = lambda self, other: Arith("-", [self, other])
    cls.__rsub__ = lambda self, other: Arith("-", [other, self])
    cls.__mul__ = lambda self, other: Arith("*", [self, other])
    cls.__rmul__ = lambda self, other: Arith("*", [other, self])
    cls.__truediv__ = lambda self, other: Arith("/", [self, other])
    cls.__rtruediv__ = lambda self, other: Arith("/", [other, self])
    cls.__round__ = lambda self, digits=None: Arith.__round__(self, digits)
    return cls


def _no_python_value(cls):
    """Символ в месте, где питон требует настоящее число.

    ``math.sqrt(len(self.tasks))`` -- обычное желание, и питон отвечал на него
    своим ``TypeError: must be real number, not Count``, то есть нашими
    внутренностями. Отказ обязан объяснять, а не показывать имя класса.
    """
    def отказ(self, *_a):
        raise DslError(
            "здесь нужно настоящее значение, а его ещё нет: считать будет база "
            "при показе.\n"
            "Сторонние библиотеки в формуле работают только над постоянными: "
            "`math.sqrt(16)` -- да, `pymorphy3.parse(self.название)` -- нет, "
            "потому что в этот момент названия ещё не существует.\n"
            "То, что зависит от записи и в запрос не переводится, объявляют "
            "устройственным действием: оно едет исходником и считается "
            "настоящим питоном у пользователя."
        )

    cls.__float__ = отказ
    cls.__int__ = отказ
    cls.__index__ = отказ
    cls.__complex__ = отказ
    return cls


def _no_python_sequence(cls):
    """``len`` и обход -- то, с чего начинается библиотека, получившая строку.

    Замерено на pymorphy3: без этого наружу выходило «object of type 'Arith'
    has no len()», то есть имя нашего класса вместо объяснения.

    Ставится **не** на ссылку: по ссылкам каркас законно ходит, разбирая вид,
    и отказ там ронял бы построение экрана. У выражения таких обходов нет.
    """
    def отказ(self, *_a):
        raise DslError(
            "здесь нужна настоящая строка, а её ещё нет: считать будет база "
            "при показе. Библиотеке, которой нужно само значение, место в "
            "устройственном действии, а не в формуле."
        )

    cls.__len__ = отказ
    cls.__iter__ = отказ
    return cls


def _cmp_ops(cls):
    """Сравнения -- всему, что считается, а не одной ссылке.

    Без этого ``len(self.tasks) > 2`` срывался питоновским ``TypeError``:
    операции были розданы ``Ref``, но не арифметике и не агрегату. Сравнить
    было нельзя **ничего** посчитанного.
    """
    cls.__eq__ = lambda self, other: Cmp("=", self, other)
    cls.__ne__ = lambda self, other: Cmp("!=", self, other)
    cls.__lt__ = lambda self, other: Cmp("<", self, other)
    cls.__le__ = lambda self, other: Cmp("<=", self, other)
    cls.__gt__ = lambda self, other: Cmp(">", self, other)
    cls.__ge__ = lambda self, other: Cmp(">=", self, other)
    # ``__eq__`` без ``__hash__`` делает объект нехешируемым, а узлы кладут в
    # множества при обходе дерева.
    cls.__hash__ = object.__hash__
    return cls


class Cmp(Expr):
    OPS = {"=", "!=", "<", "<=", ">", ">="}

    def __init__(self, op, left, right):
        if op not in self.OPS:
            raise DslError(f"Unsupported comparison operator {op!r}")
        self.op = op
        self.left = left
        self.right = right

    def _map_refs(self, fn):
        return Cmp(self.op, _map(self.left, fn), _map(self.right, fn))

    def __repr__(self):
        return f"({self.left!r} {self.op} {self.right!r})"


class _NAry(Expr):
    symbol = "?"

    def __init__(self, *parts):
        flat = []
        for p in parts:
            if isinstance(p, type(self)):
                flat.extend(p.parts)
            else:
                flat.append(p)
        self.parts = flat

    def _map_refs(self, fn):
        return type(self)(*[_map(p, fn) for p in self.parts])

    def __repr__(self):
        return f" {self.symbol} ".join(repr(p) for p in self.parts).join("()")


class And(_NAry):
    symbol = "&"


class Or(_NAry):
    symbol = "|"


class Not(Expr):
    def __init__(self, expr):
        self.expr = expr

    def _map_refs(self, fn):
        return Not(_map(self.expr, fn))

    def __repr__(self):
        return f"~{self.expr!r}"


class IsNull(Expr):
    def __init__(self, ref):
        self.ref = ref

    def _map_refs(self, fn):
        return IsNull(_map(self.ref, fn))

    def __repr__(self):
        return f"{self.ref!r}.is_null()"


class Aggregate(Expr):
    """A question about *other* records, asked from inside a view.

    ``Count(Task, record.board == item.id)`` replaces the Python tally that used
    to run before the tree was built. The difference is when it is answered: a
    tally computed in ``ui()`` is frozen into the tree, while this stays a
    question until the template is expanded, so the number follows the data.

    It is an :class:`Expr` so it can also be a condition -- ``Exists(...)`` in a
    ``visible=`` is the declarative form of "only show this section if there is
    something in it".

    Answered on the backend, in SQL: the frontend holds the template and would
    otherwise have to fetch every candidate row just to count it.
    """

    kind = "?"

    def __init__(self, model, domain=None, *, via=None, of=None, on_empty=None):
        self.model = model
        self.domain = domain
        #: Колонка, по которой считают: ``sum(self.tasks.price)`` -- это
        #: ``price``. У счёта её нет: считаются записи, а не значения.
        self.of = of
        #: Чем ответить на пустом наборе. Ставится ровно там, где его ставит
        #: питон: ``min(..., default=0)``.
        self.on_empty = on_empty
        #: Имя ссылочного поля у той модели, если агрегат считается **изнутри
        #: модели**: ``Count("Task", via="board")`` внутри ``Board`` -- это «мои
        #: задачи». В виде связь пишется доменом (``record.board == item.id``),
        #: а у вычисляемого поля писать её не о чем: запись и есть «я».
        self.via = via

    def _map_refs(self, fn):
        """``record.`` inside an aggregate belongs to *its* model, not to ours.

        ``Exists(Task, record.board == item.id)`` may sit in a view bound to no
        model at all, and its ``record.board`` is a column of Task regardless --
        resolved when the aggregate is compiled, against the model it names. So
        a walk from outside passes over those references and touches only the
        ones that are genuinely about the surroundings: the row of the enclosing
        repeat, and the state of the enclosing screen.
        """

        def outer(ref):
            return ref if isinstance(ref, RecordFieldRef) else fn(ref)

        return type(self)(self.model, _map(self.domain, outer),
                          via=self.via, of=self.of, on_empty=self.on_empty)

    @property
    def model_name(self):
        return getattr(self.model, "__name__", self.model)

    def __repr__(self):
        inner = f", {self.domain!r}" if self.domain is not None else ""
        return f"{type(self).__name__}({self.model_name}{inner})"


class Count(Aggregate):
    """How many records match. Reads as a number."""

    kind = "count"


class Exists(Aggregate):
    """Whether any record matches. Reads as a condition."""

    kind = "exists"


class Sum(Aggregate):
    """Сумма колонки. То, что пишут питоновским ``sum(...)``."""

    kind = "sum"


class Min(Aggregate):
    """Наименьшее значение колонки."""

    kind = "min"


class Max(Aggregate):
    """Наибольшее значение колонки."""

    kind = "max"


class TextExpr(Expr):
    """Выражение, записанное **строкой**: ``expr("record.n * 2 > 10")``.

    Дерево из неё собирает сборка -- один разборщик на все языки
    (`libs/js/src/build/exprtext.mjs`). До устройства строка не доезжает:
    выложенный документ несёт то же дерево, что и от питоновского DSL.

    Питону это нужно меньше всех -- у него есть перегрузка операторов, и она
    лучше во всём: её проверяет редактор, по ней работает переход к
    определению. Заведено ради привязок, которым встраивание дорого: `Expr.kt`
    покрывает семь родов узлов из четырнадцати, и арифметику на Kotlin
    объявить нечем. Но раз узел общий, он общий и здесь -- иначе договор
    описывал бы то, чего питон не умеет, и порождался бы не из кода.
    """

    def __init__(self, text):
        if not isinstance(text, str):
            raise DslError(
                f"expr(...) ждёт строку, получено {text!r}.\n"
                '    expr("record.n * 2 > 10")')
        self.text = text

    def __repr__(self):
        return f"expr({self.text!r})"

    def _map_refs(self, fn):
        return self


def expr(text):
    """Выражение строкой. Разбирает его сборка, одинаково для всех языков."""
    return TextExpr(text)


class Template(Expr):
    """Строка со ссылками внутри -- ``"Удалить «{item.name}»?"``.

    Разница с f-строкой не в записи, а в моменте. ``f"Удалить «{board.name}»?"``
    вычисляется там, где собирается дерево, и запекает имя: список переименуют,
    а вопрос останется прежним. Здесь ссылка доживает до разворота документа и
    подставляется по данным, которые есть в эту минуту.

    Части -- куски текста и ссылки вперемешку, в порядке чтения. Пустых частей
    не бывает: их порождает разбор, а не пользователь.
    """

    def __init__(self, parts):
        self.parts = list(parts)

    def _map_refs(self, fn):
        return Template([_map(p, fn) for p in self.parts])

    def __repr__(self):
        inner = "".join(
            p if isinstance(p, str) else "{" + repr(p) + "}" for p in self.parts
        )
        return f"t{inner!r}"


#: ``{item.name}``. Одна пара фигурных скобок, область и имя поля -- ничего
#: похожего на выражения ``str.format``: шаблон обязан значить одно и то же в
#: питоне, в JS и в любом третьем месте, а формат-спеки различаются везде.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\}")


def parse_template(text):
    """Текст -> :class:`Template`, если в нём есть ссылки, иначе он сам.

    Подставляется сегодня только ``item.``: это то, что нужно повторителю, и то
    единственное, на что при развороте есть ответ. ``record.`` и ``view.``
    названы в ошибке, а не забыты молча -- иначе строка приедет на экран с
    фигурными скобками и никто не поймёт, почему.
    """
    if not isinstance(text, str) or "{" not in text:
        return text
    parts, last = [], 0
    for match in _PLACEHOLDER.finditer(text):
        scope, name = match.group(1), match.group(2)
        if scope != "item":
            raise DslError(
                f"В шаблоне {text!r} ссылка '{scope}.{name}': подставляется "
                "только 'item.<поле>' -- запись повторителя. Условие о записи "
                "или о состоянии экрана говорится через visible=."
            )
        if match.start() > last:
            parts.append(text[last:match.start()])
        parts.append(ItemFieldRef(name))
        last = match.end()
    if not parts:
        return text
    if last < len(text):
        parts.append(text[last:])
    return Template(parts)


class Order:
    """One ordering term. A ``Sort`` may hold several."""

    def __init__(self, ref, direction="asc"):
        self.ref = ref
        self.direction = direction

    def _map_refs(self, fn):
        return Order(_map(self.ref, fn), self.direction)

    def __repr__(self):
        return f"{self.ref!r}.{self.direction}()"


def _map(node, fn):
    if isinstance(node, (Expr, Order)):
        return node._map_refs(fn)
    if isinstance(node, Ref):
        return fn(node)
    return node


def map_refs(node, fn):
    """Return a copy of *node* with every :class:`Ref` replaced by ``fn(ref)``."""
    return _map(node, fn)


def iter_refs(node):
    """Yield every :class:`Ref` appearing in *node*."""
    found = []

    def collect(ref):
        found.append(ref)
        return ref

    _map(node, collect)
    return found


#: Comparisons that need both sides to exist. SQL answers them with NULL, which
#: is neither true nor false; Python raises. Neither is an answer a row can be
#: drawn from, so an absent value simply fails the test.








# Арифметика прикручивается после объявления обоих классов: ``Ref`` объявлен
# выше ``Arith``, и декоратором тут не обойтись.
_arith_ops(Ref)
_arith_ops(Aggregate)
for _cls in (Ref, Aggregate, Arith):
    _more_arith_ops(_cls)
_cmp_ops(Aggregate)
_cmp_ops(Arith)
for _cls in (Ref, Aggregate, Arith):
    _no_python_value(_cls)
for _cls in (Aggregate, Arith):
    _no_python_sequence(_cls)


def _ifexp(condition, then, otherwise):
    """``a if c else b`` внутри формулы.

    Питон вычислил бы условие сразу, а его здесь ещё нет: `total` -- вопрос к
    базе, а не число. Поэтому тройное выражение не выполняется, а **записывается**
    -- и превращается в `CASE WHEN` в запросе. Ветка, которую не выбрали, в
    SQLite не вычисляется вовсе, поэтому `x / total if total else 0` безопасно:
    деления на ноль не происходит.
    """
    return Arith("if", [_as_condition(condition), then, otherwise])


class _Rewrite(ast.NodeTransformer):
    """Две записи питона, которые нельзя выполнить, но можно **записать**.

    Читаем тело метода как текст, а не выполняем как есть:

    * ``a if c else b`` -- питон проверил бы условие прямо сейчас, а проверять
      нечего: значение появится только у базы;
    * ``len(x)`` -- питон требует от него настоящее целое и другого не примет.
      Для набора связанных записей числа ещё нет, есть вопрос.

    Обе переписываются в вызовы, которые возвращают дерево. Для всего
    остального ``len`` остаётся собой: ``len("абв")`` в теле формулы посчитается
    обычным питоном, как и всё, что не трогает запись.
    """

    #: Питоновские слова, которые набор понимает по-своему: у него ещё нет
    #: значения, есть вопрос к базе. Для всего прочего они остаются собой --
    #: ``len("абв")`` в теле формулы считается обычным питоном.
    _BUILTINS = ("len", "sum", "min", "max", "str", "int", "float",
                 "any", "all")

    def visit_IfExp(self, node):
        self.generic_visit(node)
        return ast.Call(
            func=ast.Name(id="__oneframework_ifexp", ctx=ast.Load()),
            args=[node.test, node.body, node.orelse], keywords=[],
        )

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Not):
            return ast.Call(func=ast.Name(id="__oneframework_not", ctx=ast.Load()),
                            args=[node.operand], keywords=[])
        return node

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        name = "__oneframework_and" if isinstance(node.op, ast.And) else "__oneframework_or"
        result = node.values[0]
        for nxt in node.values[1:]:
            result = ast.Call(func=ast.Name(id=name, ctx=ast.Load()),
                              args=[result, nxt], keywords=[])
        return result

    def visit_JoinedStr(self, node):
        """f-строка -- склейка, и записывается склейкой.

        До этого разбора она молча печатала внутренности: на экране оказывалось
        ``record.name: Count(Task)`` вместо ``Дом: 3``.
        """
        self.generic_visit(node)
        части = []
        for кусок in node.values:
            if isinstance(кусок, ast.Constant):
                части.append(кусок)
                continue
            if кусок.format_spec is not None or кусок.conversion not in (-1, 115):
                raise DslError(
                    "в f-строке формулы пока нет ни формата, ни `!r`: "
                    "оставьте `{значение}`."
                )
            части.append(кусок.value)
        return ast.Call(func=ast.Name(id="__oneframework_format", ctx=ast.Load()),
                        args=части, keywords=[])

    def visit_GeneratorExp(self, node):
        return self._comprehension(node)

    def visit_ListComp(self, node):
        return self._comprehension(node)

    def _comprehension(self, node):
        """``sum(t.price for t in self.tasks if not t.done)``.

        Самый питоновский способ написать сумму -- и до этого разбора его не
        было вовсе: набор не перебирается, и питон срывался ``TypeError``.
        Перебора не будет и теперь; вместо него записывается то же, что писал
        бы ``filtered`` с точкой -- отбор и колонка.
        """
        self.generic_visit(node)
        if len(node.generators) != 1 or node.generators[0].is_async:
            raise DslError(
                "в формуле бывает один `for` на выражение и без `async`: "
                "остальное базе не выразить одним запросом."
            )
        gen = node.generators[0]
        if not isinstance(gen.target, ast.Name):
            raise DslError("в `for` формулы имя одно: распаковка кортежа базе "
                           "не выразима.")
        тело = ast.Lambda(
            args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=gen.target.id)],
                               kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=node.elt)
        условие = ast.Constant(value=None)
        if gen.ifs:
            слитое = gen.ifs[0]
            for ещё in gen.ifs[1:]:
                слитое = ast.Call(func=ast.Name(id="__oneframework_and", ctx=ast.Load()),
                                  args=[слитое, ещё], keywords=[])
            условие = ast.Lambda(
                args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=gen.target.id)],
                                   kwonlyargs=[], kw_defaults=[], defaults=[]),
                body=слитое)
        return ast.Call(func=ast.Name(id="__oneframework_comprehension", ctx=ast.Load()),
                        args=[gen.iter, тело, условие], keywords=[])

    def visit_Compare(self, node):
        """Три записи сравнения, которых у питона нет в виде операции.

        * **цепочка** ``1 < n < 5``: питон читает её как ``1 < n and n < 5``,
          и без разбора она срывалась ``TypeError``;
        * **``is None``**: переопределить ``is`` нельзя ничем, поэтому питон
          отвечал «нет» прямо на сборке -- условие молча становилось ложью;
        * **``in``**: перебирать нечего, но ``x in (a, b)`` -- это ``x == a or
          x == b``, и так оно и записывается.
        """
        self.generic_visit(node)
        left, parts = node.left, []
        for op, right in zip(node.ops, node.comparators):
            parts.append(self._one(op, left, right))
            left = right
        result = parts[0]
        for nxt in parts[1:]:
            result = ast.Call(func=ast.Name(id="__oneframework_and", ctx=ast.Load()),
                              args=[result, nxt], keywords=[])
        return result

    def _one(self, op, left, right):
        if isinstance(op, (ast.Is, ast.IsNot)):
            call = ast.Call(func=ast.Name(id="__oneframework_is", ctx=ast.Load()),
                            args=[left, right], keywords=[])
            return call if isinstance(op, ast.Is) else ast.Call(
                func=ast.Name(id="__oneframework_not", ctx=ast.Load()), args=[call], keywords=[])
        if isinstance(op, (ast.In, ast.NotIn)):
            call = ast.Call(func=ast.Name(id="__oneframework_in", ctx=ast.Load()),
                            args=[left, right], keywords=[])
            return call if isinstance(op, ast.In) else ast.Call(
                func=ast.Name(id="__oneframework_not", ctx=ast.Load()), args=[call], keywords=[])
        return ast.Compare(left=left, ops=[op], comparators=[right])

    #: Часы, вызванные прямо в формуле. Тело читается **один раз, на сборке**,
    #: поэтому такой вызов не спрашивает время, а запекает его: формула
    #: осталась бы сравнивать с датой сборки навсегда -- без ошибки и без
    #: следа, только с неверным числом на экране.
    _CLOCK = ("today", "now", "utcnow", "fromtimestamp", "monotonic")

    def visit_Call(self, node):
        self.generic_visit(node)
        имя = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if имя in self._CLOCK or (isinstance(node.func, ast.Attribute)
                                  and имя == "time"):
            raise DslError(
                f"`{имя}()` в формуле берёт время **сборки**, а не показа: "
                "тело читается один раз, и дата запеклась бы в него навсегда. "
                "Часы приходят параметром вызова -- см. объявленные действия; "
                "для поля по времени этой проводки пока нет."
            )
        if isinstance(node.func, ast.Name) and node.func.id in self._BUILTINS:
            return ast.Call(func=ast.Name(id=f"__oneframework_{node.func.id}", ctx=ast.Load()),
                            args=node.args, keywords=node.keywords)
        return node


def _returns(node):
    """Есть ли внутри ``return`` или ``raise``.

    И то и другое обрывает выполнение, значит ``if`` вокруг них -- ветвление
    формулы, а не обычный питон. Без ``raise`` в этом списке охрана вида
    ``if x < 0: raise ...`` уходила бы в обычное выполнение и срывалась на
    приведении условия к истине -- отказом не про то.
    """
    return any(isinstance(inner, (ast.Return, ast.Raise)) for inner in ast.walk(node))


def _as_expression(stmts, where):
    """Список предложений -> одно выражение.

    ``if`` отдельной строкой -- то же ветвление, что и тройное выражение,
    только записанное привычнее::

        if total:
            return round(done * 100 / total)
        return 0

    Выполнить его нельзя: `total` -- вопрос к базе, а не число. Зато можно
    **прочитать**: обе ветки собираются в одно выражение, и оно уезжает в
    запрос как `CASE WHEN`. Невыбранная ветка в SQLite не вычисляется, поэтому
    деления на ноль в примере выше не происходит.
    """
    prepared = []
    for i, st in enumerate(stmts):
        if isinstance(st, ast.Assign) and len(st.targets) == 1 \
                and isinstance(st.targets[0], ast.Name):
            # Присваивание **после** ветвления: выражению нужны локальные имена,
            # а предложениям там места нет. Становится моржовым -- та же строка
            # питона, только внутри выражения.
            prepared.append(ast.NamedExpr(
                target=ast.Name(id=st.targets[0].id, ctx=ast.Store()), value=st.value))
            continue
        if isinstance(st, ast.Return):
            if st.value is None:
                raise DslError(f"{where}: `return` без значения -- формула обязана "
                               "вернуть выражение.")
            return _sequence(prepared, st.value)
        if isinstance(st, ast.If) and _returns(st):
            then = _as_expression(st.body, where)
            rest = st.orelse if st.orelse else stmts[i + 1:]
            if not rest:
                raise DslError(
                    f"{where}: у `if` нет второй ветки. Формула обязана вернуть "
                    "значение при любом условии -- допишите `else` или `return` "
                    "после него.")
            return _sequence(prepared, ast.Call(
                func=ast.Name(id="__oneframework_ifexp", ctx=ast.Load()),
                args=[st.test, then, _as_expression(rest, where)], keywords=[]))
        if isinstance(st, ast.Raise):
            raise DslError(
                f"{where}: формула не умеет отказывать по условию -- её считает "
                "база, и обе ветки для неё значения. Проверку записи пишут "
                "правилом при сохранении, а не формулой поля.")
        raise DslError(
            f"{where}: `{type(st).__name__.lower()}` после ветвления записать нечем. "
            "Перенесите это выше первого `if`.")
    raise DslError(f"{where}: после ветвления нет `return` -- формула обязана "
                   "вернуть значение при любом условии.")


def _sequence(prepared, value):
    """Сначала присваивания, потом значение -- одним выражением."""
    if not prepared:
        return value
    return ast.Call(func=ast.Name(id="__oneframework_seq", ctx=ast.Load()),
                    args=prepared + [value], keywords=[])


def _flatten_returns(fn_def, where):
    """Тело метода -> обычные предложения плюс один ``return`` с выражением.

    Всё до первого ``return`` или ветвящегося ``if`` остаётся как есть: строка
    документации, присваивания, обычные циклы по известному -- это обычный
    питон, и он выполняется обычным образом.
    """
    head = []
    for i, st in enumerate(fn_def.body):
        if isinstance(st, (ast.Try, ast.While)) and _returns(st):
            слово = "try" if isinstance(st, ast.Try) else "while"
            raise DslError(
                f"{where}: `return` внутри `{слово}` формуле не выразить -- "
                "её считает база одним выражением. Оставьте `if` и `return`.")
        if isinstance(st, ast.Raise):
            raise DslError(
                f"{where}: формула не умеет отказывать -- её считает база, а не "
                "питон. Проверку записи пишут правилом при сохранении.")
        if isinstance(st, ast.Return) or (isinstance(st, ast.If) and _returns(st)):
            fn_def.body = head + [ast.Return(value=_as_expression(fn_def.body[i:], where))]
            return
        head.append(st)
    raise DslError(f"{where}: формула ничего не возвращает -- допишите `return`.")


class RelatedSet:
    """Связанные записи -- набор, у которого спрашивают на обычном питоне.

    Своих слов у набора одно: ``filtered``. Всё остальное уже сказано питоном
    и значит здесь то же, что везде::

        len(self.tasks)                 сколько
        sum(self.tasks.price)           сумма колонки
        min(...) / max(...)             наименьшее и наибольшее
        if self.tasks:                  есть ли хоть одна

    Своего ``count()`` нет, потому что это ``len``; своего ``exists()`` нет,
    потому что это ``if``; своего ``mapped()`` нет, потому что колонка берётся
    точкой. Каждое такое слово пришлось бы выучить отдельно, а выучено уже всё.

    Ближе всего это к одушному ``self.task_ids``, только считается не
    перебором, а запросом -- и потому не по разу на запись.
    """

    __slots__ = ("comodel", "inverse", "where", "column", "condition")

    def __init__(self, comodel, inverse, where=None, column=None, condition=None):
        self.comodel = comodel
        self.inverse = inverse
        #: Отбор: какие записи вообще берутся.
        self.where = where
        #: Имя колонки, если у набора её взяли точкой: ``self.tasks.price``.
        self.column = column
        #: Условие, если генератор берёт не поле, а проверку:
        #: ``all(t.price > 10 for t in self.tasks)``. Держится **отдельно** от
        #: отбора: у ``all`` отрицается именно проверка, а не отбор, и
        #: ``all(... for t in ... if t.done)`` иначе спрашивал бы не о том.
        self.condition = condition

    def filtered(self, predicate):
        """Отобрать -- лямбдой, как в Odoo: ``self.tasks.filtered(lambda t: t.done)``.

        Лямбда выполняется **один раз, на сборке**, и получает не запись, а
        символ той модели. Поэтому внутри пишут обычный питон -- ``t.done``,
        ``t.price > 100``, -- а наружу выходит условие, которое уедет в запрос.

        Отсюда и граница: перебором это не станет никогда, значит внутри лямбды
        нельзя ничего, что требует настоящего значения.
        """
        inner = predicate(_proxy_for(self.comodel))
        merged = inner if self.where is None else And(self.where, inner)
        return RelatedSet(self.comodel, self.inverse, merged, self.column,
                          self.condition)

    def __getattr__(self, name):
        """Колонка набора -- точкой, как у записи: ``self.tasks.price``.

        Отдельного ``mapped`` нет намеренно: в Odoo к полю набора и так
        обращаются точкой, а два способа написать одно -- это два способа
        ошибиться. Наружу выходит не список значений, а тот же набор, знающий
        свою колонку: сложит и сравнит его база.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        self._check(name)
        return RelatedSet(self.comodel, self.inverse, self.where, name,
                          self.condition)

    def _check(self, name):
        """Опечатка в колонке -- отказ здесь, а не сломанный запрос потом."""
        from .fields import MODEL_REGISTRY

        other = MODEL_REGISTRY.get(self.comodel)
        if other is None or name in other._fields:
            return
        raise DslError(
            f"нет поля «{name}» у модели {self.comodel}."
            + did_you_mean(name, other._fields)
        )

    def _aggregate(self, cls, what, on_empty=None):
        if self.column is None:
            raise DslError(
                f"{what} у набора записей нечего: назовите колонку точкой -- "
                f"{what}(self.<связь>.<поле>)."
            )
        return cls(self.comodel, self.where, via=self.inverse,
                   of=RecordFieldRef(self.column), on_empty=on_empty)

    def __len__(self):
        """``len()`` питон требует целым, а у нас его ещё нет.

        Отказ здесь -- не каприз: вернуть выдуманное число значило бы посчитать
        формулу молча и неверно. Настоящий ``len(...)`` в теле формулы работает
        -- его переписывает прогон (см. :class:`_Rewrite`), и до этого метода
        дело доходит только там, где переписать было нельзя.
        """
        raise DslError(
            "len() у набора работает только внутри формулы: там он "
            "превращается в запрос, а снаружи считать нечего."
        )

    def __iter__(self):
        """Перебора не будет: записи лежат в базе, а не в памяти.

        Отказ называет, чем это пишут: генератор и ``filtered`` разбираются на
        сборке и уезжают в запрос, а обычный ``for`` потребовал бы вычитать
        весь набор -- ровно тот поштучный путь, ради ухода от которого всё и
        затевалось.
        """
        raise DslError(
            "набор записей не перебирается: напишите `sum(t.поле for t in "
            "<набор>)`, `len(...)` или `.filtered(...)` -- их считает база."
        )

    def __getitem__(self, key):
        raise DslError(
            "у набора записей нет ни первой, ни срезов: порядок задаётся видом,"
            " а не формулой."
        )

    def __bool__(self):
        """``if self.tasks:`` -- вопрос к базе, а питону нужен ответ сейчас.

        Внутри формулы это переписывает прогон и получается «есть ли хоть
        одна». Здесь -- отказ, и он важнее удобства: молча вернуть ``True``
        значило бы всегда брать первую ветку, а такую ошибку на глаз не видно.
        """
        raise DslError(
            "«if <набор>:» работает только внутри формулы: там это вопрос "
            "«есть ли хоть одна», а снаружи отвечать нечем."
        )

    def __repr__(self):
        tail = f".{self.column}" if self.column else ""
        return f"self.<{self.comodel}>{tail}"


def _proxy_for(name):
    """Символ записи названной модели -- для лямбды в ``filtered``."""
    from .fields import MODEL_REGISTRY

    return _ModelProxy(MODEL_REGISTRY.get(name))


def _as_condition(value):
    """Набор в том месте, где питон ждёт «да или нет» -- это «есть ли хоть одна».

    ``if self.tasks:`` пишется ровно так же, как в питоне пишут про список, и
    значит то же самое. Своего ``exists()`` для этого не нужно.
    """
    if isinstance(value, RelatedSet):
        return Exists(value.comodel, _merge(value.where, value.condition),
                      via=value.inverse)
    return value


def _merge(where, condition):
    if condition is None:
        return where
    return condition if where is None else And(where, condition)


def _oneframework_not(value):
    """``not x`` в теле формулы. Для ссылки -- отрицание запросом, иначе обычный not."""
    value = _as_condition(value)
    if isinstance(value, (Expr, Ref, Arith)):
        return Not(value)
    return not value


def _oneframework_and(left, right):
    """``a and b`` -- в питоне это **значение**, а не «да или нет».

    ``self.name and self.name.upper()`` возвращает строку, а не истину, и
    ``self.name or "без названия"`` -- тем более. Раньше отсюда выходило
    условие, то есть ноль или единица: формула считалась, экран рисовался, и
    вместо названия показывался ``0``.

    Записывается ветвлением: ``CASE WHEN <истинно ли a> THEN b ELSE a END``.
    В условии оно работает так же, как условие, -- истинность ветвления и есть
    ``a and b``, -- а в значении даёт то, что дал бы питон.
    """
    if _symbolic(left) or _symbolic(right):
        return Arith("if", [_as_condition(left), right, left])
    return left and right


def _oneframework_or(left, right):
    if _symbolic(left) or _symbolic(right):
        return Arith("if", [_as_condition(left), left, right])
    return left or right


def _symbolic(value):
    """Это вопрос к базе, а не готовое значение питона?"""
    return isinstance(value, (Expr, Ref, Arith, RelatedSet))


def _oneframework_format(*части):
    """Куски f-строки -> шаблон, если хоть один из них -- вопрос к базе."""
    if not any(_symbolic(ч) for ч in части):
        return "".join(str(ч) for ч in части)
    return Template(list(части))


def _oneframework_comprehension(iterable, элемент, условие):
    """``<элемент> for x in <набор> if <условие>`` -> набор с отбором и колонкой.

    Не набор -- значит обычный питон, и тогда это обычный список.
    """
    if not isinstance(iterable, RelatedSet):
        значения = [элемент(x) for x in iterable]
        if условие is None:
            return значения
        return [элемент(x) for x in iterable if условие(x)]

    отобранный = iterable if условие is None else iterable.filtered(условие)
    взято = элемент(_proxy_for(iterable.comodel))
    if isinstance(взято, RecordFieldRef):
        return RelatedSet(отобранный.comodel, отобранный.inverse,
                          отобранный.where, взято.name)
    if isinstance(взято, _ModelProxy):
        # ``x for x in набор`` -- сам набор, без колонки и без проверки.
        return отобранный
    if isinstance(взято, (Expr, Cmp)):
        # ``t.price > 10 for t in ...`` -- проверка, а не колонка. Так пишут
        # под ``any`` и ``all``, и держать её надо отдельно от отбора.
        return RelatedSet(отобранный.comodel, отобранный.inverse,
                          отобранный.where, None, взято)
    if _symbolic(взято):
        # ``t.price * 2 for t in ...``: агрегат пока берёт имя колонки, и
        # делать вид, что берёт выражение, нельзя.
        raise DslError(
            "внутри генератора пока берут одно поле, а не выражение: "
            "напишите `sum(t.цена for t in ...)`, а арифметику -- снаружи."
        )
    return отобранный


def _oneframework_is(left, right):
    """``x is None`` -- вопрос о пустоте колонки, а не о тождестве объектов."""
    if isinstance(left, (Expr, Ref, Arith)) or isinstance(right, (Expr, Ref, Arith)):
        if right is None:
            return IsNull(left)
        if left is None:
            return IsNull(right)
        raise DslError(
            "`is` в формуле пишут только с None: тождество объектов базе "
            "не выразить. Сравнивайте значения через `==`."
        )
    return left is right


def _oneframework_in(value, choices):
    """``x in (a, b)`` -- это ``x == a or x == b``, и записывается так же."""
    if not isinstance(value, (Expr, Ref, Arith)):
        return value in choices
    if isinstance(choices, RelatedSet):
        raise DslError(
            "`in` по набору записей пока не переводится: напишите условие "
            "через поле связи, например `t.board == …`."
        )
    try:
        items = list(choices)
    except TypeError:
        raise DslError("`in` в формуле пишут по списку или кортежу значений.") from None
    if not items:
        # ``x in ()`` в питоне -- всегда ложь, и молчать об этом не надо.
        return False
    node = Cmp("=", value, items[0])
    for other in items[1:]:
        node = Or(node, Cmp("=", value, other))
    return node


def _oneframework_len(value):
    """``len(x)``: у набора -- счёт записей, у строки -- длина, иначе обычный len."""
    if isinstance(value, RelatedSet):
        return Count(value.comodel, _merge(value.where, value.condition),
                     via=value.inverse)
    if _symbolic(value):
        return Arith("length", [value])
    return len(value)


def _oneframework_str(*args):
    if args and _symbolic(args[0]):
        return Arith("text", [args[0]])
    return str(*args)


def _oneframework_int(*args, **kw):
    if args and _symbolic(args[0]) and not kw:
        return Arith("integer", [args[0]])
    return int(*args, **kw)


def _oneframework_float(*args):
    if args and _symbolic(args[0]):
        return Arith("real", [args[0]])
    return float(*args)


def _oneframework_any(value):
    """``any(...)`` -- «есть ли хоть одна», то же, что ``if <набор>:``."""
    if isinstance(value, RelatedSet):
        return _as_condition(value)
    if _symbolic(value):
        return _as_condition(value)
    return any(value)


def _oneframework_all(value):
    """``all(...)`` -- «нет ни одной, которая не подходит».

    Записывается отрицанием: берётся тот же отбор, а **проверка** отрицается,
    и спрашивается, пуст ли получившийся набор. Пустой набор истинен -- как
    ``all([])`` в питоне.
    """
    if isinstance(value, RelatedSet):
        if value.condition is None:
            return True             # ``all(x for x in набор)``: записи истинны
        нарушители = RelatedSet(value.comodel, value.inverse,
                                _merge(value.where, Not(value.condition)))
        return Not(_as_condition(нарушители))
    return all(value)


def _oneframework_sum(*args):
    """``sum(self.tasks.price)``. Не набор -- обычный питоновский ``sum``."""
    if args and isinstance(args[0], RelatedSet):
        if len(args) > 1:
            raise DslError("sum() у набора начального значения не принимает: "
                           "считает база, и складывать ей не с чем.")
        набор = args[0]
        if набор.condition is not None:
            # ``sum(t.done for t in ...)`` -- в питоне это счёт подходящих:
            # истина там единица.
            return Count(набор.comodel, _merge(набор.where, набор.condition),
                         via=набор.inverse)
        return набор._aggregate(Sum, "sum")
    return sum(*args)


def _oneframework_min(*args, **kw):
    """``min(self.tasks.price)``, и ``default=`` у него значит то же, что в питоне."""
    return _extremum(min, Min, "min", args, kw)


def _oneframework_max(*args, **kw):
    return _extremum(max, Max, "max", args, kw)


def _extremum(builtin, cls, what, args, kw):
    if len(args) != 1 or not isinstance(args[0], RelatedSet):
        return builtin(*args, **kw)
    extra = set(kw) - {"default"}
    if extra:
        raise DslError(f"{what}() у набора не понимает {sorted(extra)[0]!r}: "
                       "считает база, а ключа для сортировки у неё нет.")
    return args[0]._aggregate(cls, what, on_empty=kw.get("default"))


class _ModelProxy:
    """``self`` внутри формулы, знающий свою модель.

    Отличие от общего ``record`` в одном: он знает объявленные поля, поэтому
    ``self.tasks`` -- это набор связанных записей, а ``self.done`` -- ссылка на
    колонку. Общий ``record`` модели не знает и потому даёт только ссылку.
    """

    __slots__ = ("_model",)

    def __init__(self, model):
        object.__setattr__(self, "_model", model)

    def __getattr__(self, name):
        model = self._model
        field = model._fields.get(name) if model else None
        ftype = getattr(field, "ftype", None)
        if ftype in ("one2many", "many2many"):
            comodel = getattr(field, "comodel", None)
            return RelatedSet(getattr(comodel, "__name__", comodel), field.inverse)
        if ftype == "many2one":
            # Точка через связь: ``t.board.name``. Дальше по точке пойдёт уже
            # `_LinkProxy`, и он же знает, чем это кончится в запросе.
            return _LinkProxy(field, RecordFieldRef(field.column))
        if field is None and model is not None:
            # Свой метод модели -- обычный питон, только прогнанный тем же
            # разбором. Без этого `self._помощник()` срывался невнятно.
            свой = getattr(type(model), name, None) or model.__dict__.get(name)
            if callable(свой):
                return lambda *args, **kw: _traced(свой)(self, *args, **kw)
        ref = RecordFieldRef(name)
        return ref.typed(ftype) if ftype else ref


class _LinkProxy:
    """Запись **по ту сторону** ``many2one``: ``t.board.name``.

    Перебором это не станет: наружу выходит подзапрос по ключу, и он
    печатается на сборке, где имена таблиц и колонок уже известны. Поэтому
    компилятору выборки схема по-прежнему не нужна.
    """

    __slots__ = ("_field", "_key")

    def __init__(self, field, key):
        object.__setattr__(self, "_field", field)
        object.__setattr__(self, "_key", key)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        other = self._field.comodel
        if isinstance(other, str):
            from .fields import MODEL_REGISTRY
            other = MODEL_REGISTRY.get(other)
        if other is None:
            raise DslError(f"модель связи «{self._field.name}» ещё не объявлена.")
        поле = other._fields.get(name)
        if поле is None:
            raise DslError(
                f"нет поля «{name}» у модели {other.__name__}."
                + did_you_mean(name, other._fields)
            )
        if getattr(поле, "ftype", None) == "many2one":
            # Цепочка длиннее одной точки: `t.board.owner.name`.
            внутрь = _LinkProxy(поле, RecordFieldRef(поле.column))
            return _Lookup(other._table, self._key, внутрь)
        return _Lookup(other._table, self._key, RecordFieldRef(поле.column))


class _Lookup(Ref):
    """Значение из связанной таблицы по ключу. В запросе -- подзапрос по ``id``."""

    __hash__ = object.__hash__

    def __init__(self, table, key, inner):
        self.table = table
        self.key = key
        self.inner = inner

    def _map_refs(self, fn):
        return _Lookup(self.table, self.key, self.inner)

    @property
    def ref_name(self):
        return f"{self.table}.{getattr(self.inner, 'name', self.inner)}"

    def __repr__(self):
        return f"<{self.table}>.{self.inner!r}"


def _formula_scope(fn):
    """Окружение прогона: слова питона, которые набор понимает по-своему.

    Одно на всех -- и на формулу, и на метод модели, который она позвала.
    Разойдись они, помощник считался бы по другим правилам, чем формула.
    """
    scope = dict(fn.__globals__)
    scope.update({
        "__oneframework_ifexp": _ifexp,
        "__oneframework_not": _oneframework_not,
        "__oneframework_and": _oneframework_and,
        "__oneframework_or": _oneframework_or,
        "__oneframework_is": _oneframework_is,
        "__oneframework_in": _oneframework_in,
        "__oneframework_len": _oneframework_len,
        "__oneframework_sum": _oneframework_sum,
        "__oneframework_min": _oneframework_min,
        "__oneframework_max": _oneframework_max,
        "__oneframework_str": _oneframework_str,
        "__oneframework_int": _oneframework_int,
        "__oneframework_float": _oneframework_float,
        "__oneframework_any": _oneframework_any,
        "__oneframework_all": _oneframework_all,
        "__oneframework_format": _oneframework_format,
        "__oneframework_comprehension": _oneframework_comprehension,
        "__oneframework_seq": lambda *values: values[-1],
    })
    return scope


def _traced(fn):
    """Функция модели, прогнанная тем же разбором, что и формула."""
    try:
        source = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return fn
    tree = ast.parse(source)
    body = tree.body[0]
    body.decorator_list = []
    _flatten_returns(body, f"метод {fn.__name__}")
    tree = _Rewrite().visit(tree)
    ast.fix_missing_locations(tree)
    scope = _formula_scope(fn)
    exec(compile(tree, f"<метод {fn.__name__}>", "exec"), scope)
    return scope[fn.__name__]


def trace_formula(fn, model=None):
    """Прогнать формулу один раз, подставив вместо записи символ."""
    here = _ModelProxy(model) if model is not None else record
    try:
        source = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        # Исходника нет (интерактивная сессия) -- тогда без тройных выражений.
        return fn(here)
    tree = ast.parse(source)
    body = tree.body[0]
    body.decorator_list = []          # декоратор уже сработал, второй раз незачем
    _flatten_returns(body, f"формула {fn.__name__}")
    tree = _Rewrite().visit(tree)
    ast.fix_missing_locations(tree)
    scope = _formula_scope(fn)
    exec(compile(tree, f"<формула {fn.__name__}>", "exec"), scope)
    return scope[fn.__name__](here)


#: ``evaluate`` вычислял условие на записи питоном; вычисляет его устройство
#: (`libs/js/src/core/expr.js`). Перед удалением оба сверены на корпусе
#: `test_dsl` и разошлись ровно в одном -- пропущенном ключе записи, которого
#: из базы не приходит: колонка есть всегда, пустая приезжает как `null`.
