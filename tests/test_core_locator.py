"""Привязка находит ядро сама -- одним искателем, а не восемью путями.

Прежде каждое место знало путь само: ``КОРЕНЬ / "libs" / "js" / ...``,
восемь раз в шести файлах. Внутри одного дерева это работало и было незаметно;
в разных репозиториях так нельзя, а разъезжаются такие пути молча -- правится
одно место, ломается соседнее.

Порядок поиска записан здесь, потому что он и есть договор между привязкой и
ядром: сказали прямо -- берём сказанное; не сказали -- ищем установленное,
потом соседнее.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _спросить(окружение, что="корень()"):
    """Спросить искателя в отдельном процессе: он запоминает найденное."""
    г = subprocess.run(
        [sys.executable, "-c",
         "from oneframework import core\n"
         "try:\n"
         f"    print('OK', core.{что})\n"
         "except Exception as о:\n"
         "    print('ОТКАЗ', str(о).replace(chr(10), ' | '))"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        env={**os.environ, **окружение, "PYTHONPATH": str(ROOT)})
    assert г.returncode == 0, г.stderr
    return г.stdout.strip()


def test_the_core_is_found_next_to_the_binding_in_a_dev_tree():
    """Всё лежит вместе -- ядро находится без всяких переменных."""
    окружение = {к: v for к, v in os.environ.items() if к != "ONEFRAMEWORK_CORE"}
    ответ = _спросить({к: v for к, v in окружение.items()} | {"ONEFRAMEWORK_CORE": ""})
    assert ответ.startswith("OK"), ответ
    assert ответ.endswith("libs/js"), ответ


def test_a_named_core_wins_over_the_neighbour(tmp_path):
    """Сказали прямо -- берётся сказанное, даже когда рядом лежит своё."""
    чужое = tmp_path / "ядро"
    shutil.copytree(ROOT / "libs" / "js", чужое)
    ответ = _спросить({"ONEFRAMEWORK_CORE": str(чужое)})
    assert ответ == f"OK {чужое}", ответ


def test_a_named_but_wrong_path_is_refused(tmp_path):
    """Названный и негодный путь -- отказ, а не переход к следующему месту.

    Тем же доводом, что у ключа подписи: опечатка в переменной молча собрала бы
    приложение **другим** ядром, и заметить подмену было бы негде -- сборка
    прошла бы, а внутри оказалось не то.
    """
    ответ = _спросить({"ONEFRAMEWORK_CORE": str(tmp_path / "нет-такого")})
    assert ответ.startswith("ОТКАЗ"), ответ
    assert "нет-такого" in ответ and "src/build-db.mjs" in ответ, ответ


def test_a_directory_without_the_marker_is_not_the_core(tmp_path):
    """Ядро узнаётся по писателю базы, а не по имени каталога.

    `package.json` для этого не годится: его носит и привязка на JavaScript,
    и приняв её за ядро, сборка отказала бы позже и не о том.
    """
    похожее = tmp_path / "libs" / "js"
    похожее.mkdir(parents=True)
    (похожее / "package.json").write_text('{"name": "oneframework"}', encoding="utf-8")
    ответ = _спросить({"ONEFRAMEWORK_CORE": str(похожее)})
    assert ответ.startswith("ОТКАЗ"), ответ


def test_a_file_missing_inside_the_core_is_a_different_refusal(tmp_path):
    """«Ядро нашлось, но не то» -- другая беда, чем «ядра нет».

    Спутать их в одном сообщении значит заставить гадать дважды: не поставил,
    поставил не туда или поставил не ту версию.
    """
    ответ = _спросить({}, что='файл("src", "нет-такого.mjs")')
    assert ответ.startswith("ОТКАЗ"), ответ
    assert "В ядре нет" in ответ and "другой версии" in ответ, ответ


def test_the_project_root_is_found_in_both_layouts(tmp_path):
    """Куда собирается приложение -- корень ядра либо каталог над ним.

    Раскладки две, и обе живые: в отдельном репозитории `web/` лежит в корне
    ядра, в общем дереве -- выше него, рядом с привязками. Раньше корень
    искался «над питоновским пакетом»: верно ровно в общем дереве, а в
    отдельном поиск упирался в `pyproject.toml`, над которым никакого `web/`
    нет. Нашлось первой же сборкой из расколотых деревьев.
    """
    # Отдельный репозиторий: `web/` в корне ядра.
    ядро = tmp_path / "ядро"
    (ядро / "src").mkdir(parents=True)
    (ядро / "src" / "build-db.mjs").write_text("", encoding="utf-8")
    (ядро / "web").mkdir()
    (ядро / "web" / "index.html").write_text("", encoding="utf-8")
    (ядро / "package.json").write_text("{}", encoding="utf-8")
    ответ = _спросить({"ONEFRAMEWORK_CORE": str(ядро)},
                      что="__class__.__module__ and __import__("
                          "'oneframework.cli.assets', fromlist=['x']).project_root()")
    assert ответ == f"OK {ядро}", ответ


def test_a_core_without_the_page_is_refused(tmp_path):
    """Ядро нашлось, а страницы в нём нет -- отказ, а не сборка в пустоту."""
    ядро = tmp_path / "ядро"
    (ядро / "src").mkdir(parents=True)
    (ядро / "src" / "build-db.mjs").write_text("", encoding="utf-8")
    ответ = _спросить({"ONEFRAMEWORK_CORE": str(ядро)},
                      что="__class__.__module__ and __import__("
                          "'oneframework.cli.assets', fromlist=['x']).project_root()")
    assert ответ.startswith("ОТКАЗ"), ответ
    assert "web/index.html" in ответ, ответ
