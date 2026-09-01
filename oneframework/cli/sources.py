"""Откуда сборка берёт приложение.

Раньше ответ был один: импортировать ``app.py`` и взять из него ``app``. Это и
значило, что писать приложение можно только на питоне, -- не потому, что так
задумано, а потому, что здесь стоял ``importlib``.

Теперь источников столько, сколько языков. Общее у них одно: каждый умеет
напечатать **пакет объявления** (:mod:`oneframework.declaration`). Питон печатает
его из своего ``App``, JavaScript -- запуском ``node``, Kotlin -- запуском
собранной программы. Сборщик дальше не различает, откуда пакет приехал, и это
ровно то, ради чего шов проведён здесь.

Новый язык -- одна запись в :data:`SOURCES`, и ни строчки в остальном CLI.
"""

from __future__ import annotations

from .. import core

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

__all__ = ["load", "SOURCES"]

#: Корень репозитория -- отсюда берутся библиотеки языков, пока они не изданы.
ROOT = Path(__file__).resolve().parents[2]


class SourceError(SystemExit):
    """Приложение не удалось прочитать. Сообщение адресовано человеку."""


# --------------------------------------------------------------------------
# питон
# --------------------------------------------------------------------------
def from_python(path: Path):
    """``app.py`` -- как было: импортировать и взять ``app``."""
    import importlib.util
    import traceback

    from ..errors import OneFrameworkError

    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    try:
        spec.loader.exec_module(module)
    except OneFrameworkError as exc:
        raise SourceError(f"\n{type(exc).__name__}: {exc}\n") from None
    except Exception:
        traceback.print_exc()
        raise SourceError(f"\nFailed to import {path}") from None

    app = getattr(module, "app", None)
    if app is None:
        raise SourceError(
            f"{path.name} does not define 'app'. "
            "End your app with 'app = App(<RootView>)'."
        )
    return app


# --------------------------------------------------------------------------
# готовый пакет
# --------------------------------------------------------------------------
def from_bundle(path: Path):
    """Пакет объявления, уже напечатанный чьей-то библиотекой."""
    from ..declaration import DeclarationError, load as load_bundle

    try:
        return load_bundle(path)
    except DeclarationError as exc:
        raise SourceError(f"\n{path}: {exc}\n") from None


# --------------------------------------------------------------------------
# JavaScript
# --------------------------------------------------------------------------
def from_javascript(path: Path):
    """Приложение на JavaScript: спросить у ``node`` его пакет объявления."""
    node = shutil.which(os.environ.get("ONEFRAMEWORK_NODE", "node"))
    if node is None:
        raise SourceError(
            "\nПриложение написано на JavaScript, а node на этой машине нет.\n"
            "Поставьте Node.js 18 или новее.\n"
        )
    cli = core.файл("bin", "oneframework.mjs")
    return _bundle_from_command([node, str(cli), "declare", str(path)], path)


# --------------------------------------------------------------------------
# Kotlin
# --------------------------------------------------------------------------
def from_kotlin(path: Path):
    """Приложение на Kotlin: собрать его и попросить напечатать пакет.

    Делает это **ядро** (`libs/js/src/build/kotlin.mjs`), а не питон: чтобы
    объявить приложение на Kotlin, нужен компилятор Kotlin, а не язык, на
    котором написан сборщик. Питоновская копия этого шага была лишним звеном --
    человек ставил питон, чтобы собрать свой же `.kt`.

    Компиляция кэшируется по отпечатку исходников -- как и у модулей логики.
    Пересборка одного и того же приложения не должна стоить десятков секунд
    только потому, что объявление живёт на компилируемом языке.
    """
    from ..declaration import Bundle
    from ..errors import OneFrameworkError

    корень = Path(__file__).resolve().parents[2]
    скрипт = (
        "import { declare } from "
        + json.dumps(str(core.файл("src", "build", "kotlin.mjs")))
        + ";\nprocess.stdout.write(JSON.stringify(declare(process.argv[1])));"
    )
    готово = subprocess.run(
        [core.node(), "--input-type=module", "-e", скрипт, str(Path(path).resolve())],
        capture_output=True, text=True, encoding="utf-8", cwd=str(корень))
    if готово.returncode != 0:
        raise OneFrameworkError(
            f"{path}: пакет объявления не напечатался.\n{готово.stderr.strip()}")
    return Bundle(json.loads(готово.stdout), source=str(path))


def _node() -> str:
    """`node` на машине сборки. Отказ вслух: без него ядро не запустить."""
    import shutil

    from ..errors import OneFrameworkError

    найден = shutil.which("node")
    if not найден:
        raise OneFrameworkError(
            "Сборщик написан на JavaScript, а node нет. Поставьте node -- на "
            "устройство он не едет, нужен только на машине сборки.")
    return найден


#: Чем читается тот или иной вход. Расширение, а не флаг: язык виден по файлу.
SOURCES = {
    ".py": from_python,
    ".json": from_bundle,
    ".mjs": from_javascript,
    ".js": from_javascript,
    ".kt": from_kotlin,
    ".kts": from_kotlin,
}


def load(path):
    """Приложение из файла, чем бы оно ни было написано."""
    path = Path(path).resolve()
    if not path.exists():
        raise SourceError(f"No such file: {path}")
    reader = SOURCES.get(path.suffix)
    if reader is None:
        raise SourceError(
            f"\n{path.name}: не знаю, как из этого получить приложение.\n"
            f"Умею: {', '.join(sorted(SOURCES))}.\n"
        )
    return reader(path)


def _bundle_from_command(command, path: Path):
    """Запустить чужой инструмент и прочитать пакет из его вывода."""
    from ..declaration import Bundle, DeclarationError

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SourceError(
            f"\n{path}: приложение не напечатало объявление.\n"
            f"{result.stderr.strip() or result.stdout.strip()}\n"
        )
    try:
        doc = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise SourceError(
            f"\n{path}: вместо пакета объявления пришло вот это:\n"
            f"{result.stdout[:800]}\n"
        ) from None
    try:
        return Bundle(doc, source=str(path))
    except DeclarationError as exc:
        raise SourceError(f"\n{path}: {exc}\n") from None
