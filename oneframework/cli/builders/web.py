"""Сборка веба: подготовить то, что умеет только питон, и позвать ядро.

Сборщик переехал на JavaScript (`libs/js/src/build/`). Ядро -- договор, сборка
и рантайм -- должно ставиться без привязки к языку: человек, пишущий на Kotlin,
не обязан ставить питон, чтобы собрать своё приложение.

Здесь остаётся то, что без питона не сделать: напечатать пакет объявления
(включая прогон демо-данных), привезти интерпретатор на устройство, собрать
модули Kotlin через TeaVM и собрать исходники виджетов модулей. Всё
остальное -- база, манифест, значки, конфиг, vite, список для офлайна --
делает ядро, и делает одинаково для всех трёх языков.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ... import core
from .. import python_runtime
from ..assets import project_root

#: files that never belong in the service worker precache list
#: Здесь жили `write_build_config`, `inject_service_worker`, `SKIP_PRECACHE` и
#: `_npx` -- всё это делает теперь ядро на JavaScript
#: (`libs/js/src/build/web.mjs`). Переезд шёл под двусторонней сверкой
#: (`tests/test_js_web_build.py`): порядок обхода `dist/` она и поймала --
#: питон сортирует пути по частям, а не по строке.


def prepare(app_file: Path, app) -> Path:
    """То, что умеет только питон. Остальное делает ядро на JavaScript."""
    root = project_root()
    # Питон на устройстве -- только если приложение его объявило. Молча возить
    # тринадцать мегабайт ради возможности, которой никто не просил, нельзя.
    опись = python_runtime.vendor(root, getattr(app, "python_packages", []))
    if опись["packages"]:
        print(f"Питон на устройстве: {', '.join(опись['packages'])}")
    return root


def _пакет_и_добавка(app_file: Path, app, каталог: Path):
    """Пакет объявления и то, что привязка передаёт ядру готовым.

    Виджеты и стили модулей едут исходником, а не ссылкой: файлы лежат в
    дереве приложения, а не на веб-сервере, и так они одинаково работают
    офлайн и внутри APK. Найти их умеет только питоновская привязка -- она их и
    находит.
    """
    from ...declaration import Bundle, declare

    пакет = app.doc if isinstance(app, Bundle) else declare(app, _seed_of(app_file))
    файл = каталог / "пакет.json"
    файл.write_text(json.dumps(пакет, ensure_ascii=False, default=str), encoding="utf-8")

    def статика(suffix):
        out = []
        for path in app.static_files(suffix):
            try:
                out.append({"name": str(path), "source": path.read_text(encoding="utf-8")})
            except OSError as exc:
                out.append({"name": str(path), "error": str(exc)})
        return out

    добавка = каталог / "добавка.json"
    добавка.write_text(json.dumps({"scripts": статика(".js"), "styles": статика(".css")},
                                  ensure_ascii=False), encoding="utf-8")
    return файл, добавка


def _позвать_ядро(root: Path, app_file: Path, app, аргументы):
    """Отдать пакет сборщику на JavaScript и дождаться его.

    Через файл, а не через stdin: сборщик запускает vite, и его вывод должен
    идти человеку без пересказа. Пересказанный чужой вывод теряет цвет,
    прогресс и порядок строк.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as каталог:
        пакет, добавка = _пакет_и_добавка(app_file, app, Path(каталог))
        сборщик = core.файл("src", "build", "cli.mjs")
        команда = [core.node(), str(сборщик), "web", str(пакет),
                   "--root", str(root), "--extra", str(добавка), *аргументы]
        готово = subprocess.run(команда, cwd=str(root))
        if готово.returncode != 0:
            raise SystemExit(f"command failed: {' '.join(команда)}")


#: `_собрать_модули` жила здесь -- компиляция объявленных модулей в WebAssembly.
#: Делает это теперь ядро (`libs/js/src/build/web.mjs`), и правильно: просит
#: модуль **пакет объявления**, а печатает пакет кто угодно. Пока шаг жил тут,
#: человек с приложением на Kotlin ставил питон, чтобы скомпилировать свой же
#: Kotlin. Порт шёл под сверкой байтов модуля (`tests/test_js_teavm.py`).


def _seed_of(app_file: Path):
    """``seed()`` рядом с ``app.py``, если он там есть.

    Демо-данные заполняются на сборке, а не на первом запуске: без питона на
    устройстве заполнять их некому, и это правильно -- seed по смыслу принадлежит
    сборке, а не рантайму.
    """
    import importlib

    # Только у питоновского приложения. У пакета объявления соседнего `seed.py`
    # нет и быть не может -- а слепой импорт по имени подхватил бы чужой модуль
    # с этим именем и залил бы в приложение чужие данные.
    if app_file.suffix != ".py":
        return None
    try:
        return getattr(importlib.import_module("seed"), "seed", None)
    except ModuleNotFoundError:
        return None


#: Здесь жили `write_build_config`, `inject_service_worker`, `SKIP_PRECACHE` и
#: `_npx` -- всё это делает теперь ядро на JavaScript
#: (`libs/js/src/build/web.mjs`). Переезд шёл под двусторонней сверкой
#: (`tests/test_js_web_build.py`): порядок обхода `dist/` она и поймала --
#: питон сортирует пути по частям, а не по строке.


def dev(app_file: Path, app, port: int = 5173, open_browser: bool = False):
    root = prepare(app_file, app)
    аргументы = ["--dev", "--port", str(port)] + (["--open"] if open_browser else [])
    _позвать_ядро(root, app_file, app, аргументы)


def build(app_file: Path, app) -> Path:
    root = prepare(app_file, app)
    _позвать_ядро(root, app_file, app, [])
    return root / "dist"


#: Здесь жили `write_build_config`, `inject_service_worker`, `SKIP_PRECACHE` и
#: `_npx` -- всё это делает теперь ядро на JavaScript
#: (`libs/js/src/build/web.mjs`). Переезд шёл под двусторонней сверкой
#: (`tests/test_js_web_build.py`): порядок обхода `dist/` она и поймала --
#: питон сортирует пути по частям, а не по строке.
