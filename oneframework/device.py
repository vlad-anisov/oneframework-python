"""Логика, которую считает устройство.

Она **принадлежит модели**, и объявляется на ней -- методом, как и положено
поведению записи::

    class Note(Model):
        title = String("Текст", required=True)
        details = Text("Подробности")

        def summary(self):
            for record in self:
                record.details = f"{len(record.title.split())} слов"

``self`` -- **набор записей**, по которым действие позвали; правка -- обычное
присваивание, возвращать ничего не надо.

Помечать метод нечем и незачем. Метод модели -- это поведение записи, а
другого поведения у неё не бывает: считает его устройство, потому что другого
исполнителя нет. Декоратор сообщал бы единственно возможное -- и закрывал бы
собой то, чем метод является.

Не действия только два рода имён, и оба узнаются по правилам самого питона:
начинающиеся с ``_`` (в питоне это и значит «не наружу»; вычисляемые поля
пишутся ими) и ``staticmethod``/``classmethod``/``property`` (у них нет набора
записей первым доводом).

Уточнить всё же можно -- ``@action(writes=[details])``, -- если хочется сузить
список полей или подписать действие иначе. Это качественное прилагательное к
методу, а не разрешение быть методом.

В кнопке пишется ``action=record.summary()``: скобки значат «на этой записи»,
а не «прямо сейчас». Ни строки с именем, ни обёртки -- опечатку находит
редактор, ещё до сохранения файла.

**Тело едет исходником, поэтому оно обязано быть самодостаточным.** Всё, что
функции нужно, она импортирует внутри себя: на устройстве от файла приложения
не останется ничего, кроме этой функции. Замыкание поймано и отвергнуто здесь
же -- иначе на устройстве оно упало бы `NameError`, и сильно позже.

Языкам, которые **компилируются**, тело в файле приложения написать нельзя:
объявление собирается под одну цель, а логика -- под другую (Kotlin: JVM
против WebAssembly). Там логика лежит своим файлом, а на модели объявляется
ссылка на него::

    SUMMARY = OnDevice("logic/Summary.kt", "summary", Note)

Файл -- настоящий: лежит рядом, открывается редактором как обычный исходник на
своём языке, компилируется отдельно.
"""

from __future__ import annotations

import inspect
import textwrap
from pathlib import Path

from .errors import DslError

__all__ = ["OnDevice", "action", "DeviceAction"]

#: Расширение -> как это доставляется. Три способа запуска, и они не
#: взаимозаменяемы: текст исполняет интерпретатор (свой или встроенный),
#: модуль -- движок WebAssembly.
СПОСОБЫ = {
    ".py": ("python", "исходник, его исполняет Pyodide"),
    ".js": ("js", "исходник, его исполняет сам webview"),
    ".mjs": ("js", "исходник, его исполняет сам webview"),
    ".kt": ("wasm", "компилируется в WebAssembly на сборке"),
    ".rs": ("wasm", "компилируется в WebAssembly на сборке"),
    ".c": ("wasm", "компилируется в WebAssembly на сборке"),
    ".cpp": ("wasm", "компилируется в WebAssembly на сборке"),
}


#: Обвязка, которая едет на устройство вместе с телом метода.
#:
#: Она превращает кадр -- словарь, приехавший по проводу, -- в **набор
#: записей**, и обратно. Из-за неё метод пишется так, как поведение записи и
#: должно писаться: `for record in self`, правка присваиванием, ничего не
#: возвращать. Без неё пришлось бы читать `frame["records"]` и складывать
#: ответ руками, то есть говорить с устройством на языке протокола, а не на
#: языке предметной области.
#:
#: Едет исходником рядом с телом, а не лежит в рантайме устройства, и это
#: осознанно: объявление обязано быть самодостаточным. Устройство исполняет
#: то, что ему прислали, и ничего не должно знать заранее -- иначе рантайм и
#: объявление становятся двумя половинами, которые надо обновлять вместе.
PYTHON_SHIM = '''\
class Record:
    """Одна запись. Читается точкой, правится присваиванием."""

    def __init__(self, values, writes):
        object.__setattr__(self, "_values", dict(values))
        object.__setattr__(self, "_writes", tuple(writes))
        object.__setattr__(self, "_changed", {})

    def __getattr__(self, name):
        try:
            return object.__getattribute__(self, "_values")[name]
        except KeyError:
            raise AttributeError(
                "у записи нет поля %r; приехали: %s"
                % (name, ", ".join(sorted(object.__getattribute__(self, "_values"))))
            ) from None

    def __setattr__(self, name, value):
        writes = object.__getattribute__(self, "_writes")
        if name not in writes:
            raise AttributeError(
                "поле %r этому действию писать не разрешено; разрешены: %s. "
                "Считает действие, а пишет хост -- список закрытый намеренно."
                % (name, ", ".join(writes) or "ни одного")
            )
        object.__getattribute__(self, "_values")[name] = value
        object.__getattribute__(self, "_changed")[name] = value

    def get(self, name, default=None):
        return object.__getattribute__(self, "_values").get(name, default)


class Records:
    """Набор записей -- то, чем действие зовут. Это и есть `self`."""

    def __init__(self, rows, writes):
        self._rows = [Record(row, writes) for row in rows]

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, index):
        return self._rows[index]

    def __bool__(self):
        return bool(self._rows)

    def changed(self):
        out = []
        for row in self._rows:
            changed = object.__getattribute__(row, "_changed")
            if changed:
                out.append(dict(changed, id=row.id))
        return out
'''

#: Имя точки входа в собранном модуле. Не имя метода: метод остаётся собой, а
#: точка входа -- это обвязка вокруг него.
ENTRY = "__oneframework_entry"


class DeviceAction:
    """Метод модели, который считает устройство.

    Живёт в теле класса модели и знает своё имя оттуда же, откуда его знает
    питон, -- из ``__set_name__``. Поэтому на него можно сослаться:
    ``Logic(Note.summary)`` -- обычное обращение к атрибуту, и опечатка в нём
    не доживает до запуска.
    """

    def __init__(self, fn, *, writes=None, label=None, name=None, args=None,
                 returns=None):
        self.fn = fn
        self.entry = fn.__name__
        # Что действию позволено записать. По умолчанию -- поля своей модели,
        # и перечислять их не надо: список выводится, а не пишется руками.
        #
        # Рукописный список был пересказом тела: там и так стоит
        # `record.details = ...`. Пересказ рано или поздно расходится с
        # пересказанным, и расходится молча -- действие перестаёт писать поле,
        # которое, судя по коду, пишет.
        #
        # Сузить всё ещё можно -- `@action(writes=[details])`, -- если хочется
        # сказать вслух, что действие трогает только это. Но это выбор, а не
        # обряд.
        self._writes = None if writes is None else list(writes)
        self.label = label or fn.__name__
        self.args = args
        self.returns = returns
        self.model_name = None
        self.owner = None
        self.name = name

    def __set_name__(self, owner, attribute):
        self.entry = attribute
        if owner is None:
            return
        self.owner = owner
        self.model_name = owner.__name__
        if self.name is None:
            self.name = f"{owner.__name__}.{attribute}"

    @property
    def writes(self):
        """Имена полей, которые методу позволено записать.

        Спрашивается поздно -- когда модель уже собрана. В теле класса ни у
        поля нет имени, ни у модели нет полей.
        """
        if self._writes is None:
            модель = self.owner
            if модель is None:
                return []
            return [и for и, поле in модель._fields.items() if not поле.system]
        return [и.name if hasattr(и, "ftype") else и for и in self._writes]

    def body(self):
        """Тело метода так, как оно написано, -- без строки декоратора.

        Декоратор на устройстве не существует: там нет ни модели, ни
        фреймворка, только эта функция. Оставить его значило бы отправить
        исходник, который не исполнится.
        """
        if self.fn.__code__.co_freevars:
            raise DslError(
                f"{self.name}: тело едет на устройство исходником, а оно "
                f"замыкает {', '.join(self.fn.__code__.co_freevars)}. На "
                "устройстве этих имён нет. Всё нужное метод обязан взять сам "
                "-- импортом внутри себя или из набора записей."
            )
        текст = textwrap.dedent(inspect.getsource(self.fn))
        строки = текст.splitlines()
        начало = next(i for i, с in enumerate(строки)
                      if с.lstrip().startswith(("def ", "async def ")))
        return "\n".join(строки[начало:]) + "\n"

    def source(self):
        """Готовый модуль: обвязка, тело метода и точка входа.

        Собирается здесь, а не на устройстве, потому что объявление обязано
        быть самодостаточным: устройство исполняет присланное и ничего не
        знает заранее.
        """
        writes = ", ".join(repr(и) for и in self.writes)
        return (
            f"{PYTHON_SHIM}\n"
            f"{self.body()}\n"
            f"def {ENTRY}(frame):\n"
            f"    records = Records(frame.get('records') or [], ({writes},))\n"
            f"    {self.entry}(records)\n"
            f"    return {{'records': records.changed()}}\n"
        )

    def declaration(self):
        """То же объявление, что даёт :func:`OnDevice`, -- их читают одинаково."""
        объявление = {
            "name": self.name,
            "label": self.label,
            "args": self.args or [{"name": "ids", "type": "ids"}],
            "returns": self.returns or [{"name": "records", "type": "json"}],
            "language": "python",
            "python": {
                "entry": ENTRY,
                "writes": list(self.writes),
                "source": self.source(),
            },
        }
        if self.model_name:
            объявление["model"] = self.model_name
        return объявление

    def __repr__(self):
        return f"<логика {self.name}>"


def action(fn=None, *, writes=None, label=None, name=None, args=None,
           returns=None):
    """Метод модели -- действие над её записями.

    Пишется голым: ``@action``. Скобки нужны, только если хочется что-то
    уточнить -- сузить ``writes`` или подписать действие иначе, чем зовётся
    метод.

    Не ``on_device``: место исполнения здесь одно, и имя, сообщающее
    единственно возможное, закрывает собой то, чем метод является.

    ``self`` -- набор записей, по которым действие позвали. Правка --
    присваивание, возвращать нечего.
    """
    def decorator(func):
        return DeviceAction(func, writes=writes, label=label, name=name,
                            args=args, returns=returns)
    return decorator(fn) if fn is not None else decorator


def OnDevice(файл, entry, model=None, *, writes=(), label=None, name=None,
             args=None, returns=None):
    """Объявить логику, которую считает **устройство**.

    ``файл`` -- путь относительно того, кто вызвал: так же, как питон ищет
    соседний модуль, и по той же причине -- логика лежит рядом с приложением,
    а не там, откуда его запустили.

    ``entry`` -- имя функции в файле. ``writes`` -- какие поля действию
    позволено записать; список закрытый, потому что считает оно, а пишет хост.
    """
    путь = _рядом_с_вызвавшим(файл)
    вид, _ = СПОСОБЫ.get(путь.suffix, (None, None))
    if вид is None:
        raise DslError(
            f"не знаю, чем исполнять «{путь.name}». Умею: "
            + ", ".join(sorted(СПОСОБЫ)) + "."
        )
    if not путь.exists():
        raise DslError(f"нет файла логики: {путь}")

    имя_модели = getattr(model, "__name__", model)
    объявление = {
        "name": name or f"{имя_модели}.{entry}",
        "label": label or entry,
        "args": args or [{"name": "ids", "type": "ids"}],
        "returns": returns or [{"name": "records", "type": "json"}],
        "language": _язык(путь.suffix),
    }
    if имя_модели:
        объявление["model"] = имя_модели

    if вид == "wasm":
        # Байты кладёт сборка: 624 КБ машинного кода строкой в таблице
        # определений возить незачем.
        объявление["wasm"] = {
            "module": путь.stem, "entry": entry, "writes": list(writes),
            "sources": [str(путь)],
        }
    else:
        объявление[вид] = {
            "entry": entry, "writes": list(writes),
            "source": путь.read_text(encoding="utf-8"),
        }
    return объявление


def _язык(суффикс):
    return {".py": "python", ".js": "javascript", ".mjs": "javascript",
            ".kt": "kotlin", ".rs": "rust", ".c": "c", ".cpp": "c++"}[суффикс]


def _рядом_с_вызвавшим(файл):
    """Путь относительно файла, который позвал -- не относительно `cwd`.

    Иначе приложение собиралось бы только из своей папки, а из соседней молча
    не находило бы логику.
    """
    путь = Path(файл)
    if путь.is_absolute():
        return путь
    кадр = inspect.stack()[2]
    return (Path(кадр.filename).parent / путь).resolve()
