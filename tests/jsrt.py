"""Разговор с рантаймом приложения на JS -- тем, что стоит на устройстве."""

from __future__ import annotations

import atexit
import json
import subprocess
import tempfile
from pathlib import Path

from jsrel import ОтказJs, needs_node

ROOT = Path(__file__).resolve().parents[1]
ХОСТ = ROOT / "tests" / "parity" / "rt_host.mjs"

__all__ = ["Рантайм", "ОтказJs", "needs_node"]

class Рантайм:
    def __init__(self, app, seed=None, db_file=None):
        self._каталог = None
        if db_file is None:
            self._каталог = tempfile.TemporaryDirectory()
            db_file = Path(self._каталог.name) / "app.db"
            _выложить(app, db_file, seed)
        self._процесс = subprocess.Popen(
            ["node", str(ХОСТ)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", cwd=str(ROOT),
            bufsize=1,
        )
        atexit.register(self.close)
        self.snapshot_at_boot = self.call("open", str(db_file),
                                          [s.ir() for s in app.screens])

    def call(self, op, *args):
        """Спросить рантайм. Отказ приезжает исключением, смерть -- громко."""
        if self._процесс.poll() is not None:
            raise RuntimeError("Хост рантайма уже закрыт")
        self._процесс.stdin.write(
            json.dumps({"op": op, "args": list(args)}, ensure_ascii=False) + "\n")
        self._процесс.stdin.flush()
        строка = self._процесс.stdout.readline()
        if not строка:
            raise RuntimeError(f"Хост рантайма умер на {op}:\n{self._процесс.stderr.read()}")
        ответ = json.loads(строка)
        if "error" in ответ:
            raise ОтказJs(ответ["error"]["name"], ответ["error"]["message"])
        return ответ["ok"]

    # -- то, что проверки спрашивают чаще всего ----------------------------
    @property
    def db(self):
        return _База(self)

    def snapshot(self):
        return self.call("snapshot")

    def dispatch(self, событие):
        return self.call("dispatch", событие)

    @property
    def stacks(self):
        return {к: [Кадр(f) for f in v] for к, v in self.snapshot()["stacks"].items()}

    @property
    def active(self):
        return self.snapshot()["active"]

    @property
    def stack(self):
        return [Кадр(к) for к in self.call("stack")]

    def push(self, вид, **опции):
        return Кадр(self.call("push", вид, опции))

    def pop(self):
        return [Кадр(к) for к in self.call("pop")]

    def touch(self, модель):
        return self.call("touch", _имя(модель))

    def find_list(self, list_id):
        return self.call("find_list", list_id)

    def current(self):
        return Кадр(self.call("current"))

    def count(self, модель):
        return self.call("count", _имя(модель))

    def close(self):
        if self._процесс is not None and self._процесс.poll() is None:
            self._процесс.stdin.close()
            self._процесс.wait(timeout=5)
        if self._каталог is not None:
            self._каталог.cleanup()
            self._каталог = None

def _выложить(app, файл, seed):
    from conftest import собрать_базу
    from oneframework.declaration import Bundle, declare

    собрать_базу(Bundle(declare(app, seed)), Path(файл))

def _имя(модель):
    """Модель -- по имени: за проводом питоновского класса не передать."""
    return модель if isinstance(модель, str) else модель.__name__

class Кадр:
    def __init__(self, данные):
        self.__dict__.update(данные or {})

    def __repr__(self):
        return f"Кадр({self.__dict__.get('view')}, {self.__dict__.get('id')})"

class _База:
    """База хоста -- тем же лицом, что питоновская: `count`, `read`, `all`."""
    def __init__(self, рт):
        self._рт = рт

    def count(self, модель):
        return self._рт.call("count", _имя(модель))

    def read(self, модель, record_id):
        return self._рт.call("read", _имя(модель), record_id)

    def all(self, модель):
        return self._рт.call("all", _имя(модель))

    def create(self, модель, значения):
        return self._рт.call("create", _имя(модель), значения)

    def write(self, модель, record_id, значения):
        return self._рт.call("write", _имя(модель), record_id, значения)
