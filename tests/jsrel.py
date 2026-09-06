"""Разговор с компилятором на JS -- один процесс на всю сюиту."""

from __future__ import annotations

import atexit
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ХОСТ = ROOT / "tests" / "parity" / "rel_host.mjs"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="нет node")

_процесс = None

class ОтказJs(Exception):
    """Отказ компилятора -- ответ, а не поломка: половина правил -- отказы."""
    def __init__(self, name, message):
        super().__init__(f"{name}: {message}")
        self.name = name
        self.message = message

def _хост():
    global _процесс
    if _процесс is None or _процесс.poll() is not None:
        _процесс = subprocess.Popen(
            ["node", str(ХОСТ)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", cwd=str(ROOT),
            bufsize=1,
        )
        atexit.register(_закрыть)
    return _процесс

def _закрыть():
    global _процесс
    if _процесс is not None and _процесс.poll() is None:
        _процесс.stdin.close()
        _процесс.wait(timeout=5)
    _процесс = None

def call(op, *args):
    п = _хост()
    п.stdin.write(json.dumps({"op": op, "args": list(args)}, ensure_ascii=False) + "\n")
    п.stdin.flush()
    строка = п.stdout.readline()
    if not строка:
        оставшееся = п.stderr.read() if п.stderr else ""
        raise RuntimeError(f"Хост компилятора умер на {op}:\n{оставшееся}")
    ответ = json.loads(строка)
    if "error" in ответ:
        raise ОтказJs(ответ["error"]["name"], ответ["error"]["message"])
    return ответ["ok"]

def refusal(op, *args):
    """Слова отказа. Если компилятор не отказал -- это провал проверки."""
    try:
        got = call(op, *args)
    except ОтказJs as отказ:
        return отказ.message
    raise AssertionError(f"{op} не отказал, а ответил {got!r}")

