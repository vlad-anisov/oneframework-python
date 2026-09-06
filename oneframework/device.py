"""Логика, которую считает устройство."""

from __future__ import annotations

import inspect
import textwrap
from pathlib import Path

from .errors import DslError

__all__ = ["OnDevice", "action", "DeviceAction"]

СПОСОБЫ = {
    ".py": ("python", "исходник, его исполняет Pyodide"),
    ".js": ("js", "исходник, его исполняет сам webview"),
    ".mjs": ("js", "исходник, его исполняет сам webview"),
    ".kt": ("wasm", "компилируется в WebAssembly на сборке"),
    ".rs": ("wasm", "компилируется в WebAssembly на сборке"),
    ".c": ("wasm", "компилируется в WebAssembly на сборке"),
    ".cpp": ("wasm", "компилируется в WebAssembly на сборке"),
}

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

ENTRY = "__oneframework_entry"

class DeviceAction:
    def __init__(self, fn, *, writes=None, label=None, name=None, args=None,
                 returns=None):
        self.fn = fn
        self.entry = fn.__name__
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
        if self._writes is None:
            модель = self.owner
            if модель is None:
                return []
            return [и for и, поле in модель._fields.items() if not поле.system]
        return [и.name if hasattr(и, "ftype") else и for и in self._writes]

    def body(self):
        """Тело метода так, как оно написано, -- без строки декоратора."""
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
    def decorator(func):
        return DeviceAction(func, writes=writes, label=label, name=name,
                            args=args, returns=returns)
    return decorator(fn) if fn is not None else decorator

def OnDevice(файл, entry, model=None, *, writes=(), label=None, name=None,
             args=None, returns=None):
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
    """Путь относительно файла, который позвал -- не относительно `cwd`."""
    путь = Path(файл)
    if путь.is_absolute():
        return путь
    кадр = inspect.stack()[2]
    return (Path(кадр.filename).parent / путь).resolve()
