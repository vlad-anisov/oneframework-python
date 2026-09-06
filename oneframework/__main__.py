"""Дверь, в которую стучится ядро, когда приложение написано на питоне."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

def _приложение(путь: Path):
    """``app`` из соседнего файла. Импортом: ``ui`` -- это программа."""
    import importlib.util

    родитель = str(путь.parent)
    if родитель not in sys.path:
        sys.path.insert(0, родитель)
    спец = importlib.util.spec_from_file_location(путь.stem, путь)
    модуль = importlib.util.module_from_spec(спец)
    # В `sys.modules` до исполнения, а не после: объявление модели ищет свой
    # модуль по имени, чтобы записать, откуда она.
    sys.modules[путь.stem] = модуль
    спец.loader.exec_module(модуль)
    app = getattr(модуль, "app", None)
    if app is None:
        raise SystemExit(
            f"{путь}: нет `app`. Файл приложения заканчивается\n"
            "    app = App(Экран, title='…')")
    return app

def _посев(путь: Path):
    """``seed()`` рядом с ``app.py``, если он там есть."""
    рядом = путь.parent / "seed.py"
    if not рядом.exists():
        return None
    import importlib

    try:
        return getattr(importlib.import_module("seed"), "seed", None)
    except ModuleNotFoundError:
        return None

def _добавка(app) -> dict:
    def статика(суффикс):
        из = []
        for путь in app.static_files(суффикс):
            try:
                из.append({"name": str(путь), "source": путь.read_text(encoding="utf-8")})
            except OSError as беда:
                из.append({"name": str(путь), "error": str(беда)})
        return из

    return {"scripts": статика(".js"), "styles": статика(".css")}

def declare(доводы) -> int:
    from .declaration import Bundle, declare as объявить

    путь = Path(доводы.app).resolve()
    app = _приложение(путь)
    пакет = app.doc if isinstance(app, Bundle) else объявить(app, _посев(путь))

    куда = Path(доводы.out)
    куда.mkdir(parents=True, exist_ok=True)
    (куда / "пакет.json").write_text(
        json.dumps(пакет, ensure_ascii=False, default=str), encoding="utf-8")
    (куда / "добавка.json").write_text(
        json.dumps(_добавка(app), ensure_ascii=False), encoding="utf-8")

    from .model.defs import SKIPPED

    if SKIPPED:
        (куда / "пропуски.json").write_text(
            json.dumps({и: str(б) for и, б in SKIPPED.items()}, ensure_ascii=False),
            encoding="utf-8")

    if доводы.root:
        from .cli import python_runtime

        опись = python_runtime.vendor(Path(доводы.root),
                                      getattr(app, "python_packages", []))
        if опись["packages"]:
            print(f"Питон на устройстве: {', '.join(опись['packages'])}")
    return 0

def main(argv=None) -> int:
    разбор = argparse.ArgumentParser(
        prog="python -m oneframework",
        description="Напечатать пакет объявления. Собирает -- ядро: npx oneframework")
    под = разбор.add_subparsers(dest="команда", required=True)
    p = под.add_parser("declare", help="написать пакет объявления и добавку")
    p.add_argument("app", help="файл приложения на питоне")
    p.add_argument("--out", required=True, help="каталог для пакета и добавки")
    p.add_argument("--root", default=None, help="корень сборки: везти ли питон")
    доводы = разбор.parse_args(argv)
    return declare(доводы)

if __name__ == "__main__":
    raise SystemExit(main())
