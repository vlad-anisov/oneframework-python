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
    "Expr",
    "ItemFieldRef",
    "Order",
    "RecordFieldRef",
    "Ref",
    "Template",
    "UNSET",
    "ViewFieldRef",
    "item",
    "iter_refs",
    "map_refs",
    "parse_template",
    "record",
    "view",
]


class _Unset:
    """UI state that the user has not chosen yet.

    Deliberately distinct from ``None``/SQL ``NULL``: a comparison against
    UNSET is *dropped* from the query instead of becoming ``IS NULL``.
    """

    _instance = None


    def __repr__(self):
        return "UNSET"

    def __bool__(self):
        return False


UNSET = _Unset()


class Expr:
    """Base class for boolean domain nodes."""


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


    def is_null(self):
        """Explicit SQL ``NULL`` test (never implied by UNSET)."""

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


    def __getattr__(self, name):
        return _string_method(self, name, f"поля «{self.name}»")

    def __repr__(self):
        return f"record.{self.name}"


#: Слова питона для строк -> операции, которые SQLite умеет **точно**.
#: Чего нет -- отказывает по имени, а не делает похоже: ``upper`` над
#: кириллицей SQLite не умеет вовсе, и молчаливое «АБВ -> абв без изменений»
#: было бы хуже отказа.


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
