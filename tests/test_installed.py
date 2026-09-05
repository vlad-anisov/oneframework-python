"""Пакет обязан работать там, где его поставят, а не только в дереве.

Сюита гоняется в монорепозитории, где рядом с пакетом лежит всё: `protocol/`,
`libs/js`, примеры. У человека рядом не лежит ничего -- у него
``site-packages``. Разница эта не теоретическая: 02.09.2026 таблица типов
переехала из классов полей в `protocol/field-types.json`, привязка стала
читать её **при ввозе**, а в колесо файл не попадал. `pip install oneframework`
давал пакет, который не ввозится, -- и все 349 проверок при этом были зелёные,
потому что ни одна не спрашивала про установленный пакет.

Отсюда две проверки, и обе про одно: собрать настоящее колесо и ввезти его
оттуда, где нет дерева.

Дорого -- около полуминуты на сборку. Дешевле не выходит: подделка
(«притворимся, что дерева нет») проверяла бы нашу догадку о том, чего не
хватает, а не то, что вправду доехало.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    shutil.which("python3") is None, reason="python3 недоступен")


#: Что нужно, чтобы собрать колесо. Договор (`protocol/`) сюда не входит
#: намеренно: если копии внутри пакета нет, колесо обязано выйти без таблицы, а
#: не подобрать её из дерева.
ДЛЯ_СБОРКИ = ("pyproject.toml", "oneframework", "README.md", "LICENSE")


@pytest.fixture(scope="module")
def колесо(tmp_path_factory):
    """Собрать колесо из **чистой копии** дерева.

    Копия, а не сам корень: рядом с ним заводятся `build/` и
    `oneframework.egg-info`, и setuptools берёт из них. Проба это и поймала --
    снятая из `pyproject.toml` таблица всё равно попадала в колесо, потому что
    её подкладывал вчерашний `build/`. Сторож, которого обманывает мусор
    прошлой сборки, не сторож.
    """
    дерево = tmp_path_factory.mktemp("дерево")
    for имя in ДЛЯ_СБОРКИ:
        источник = ROOT / имя
        if not источник.exists():
            continue
        if источник.is_dir():
            shutil.copytree(источник, дерево / имя,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(источник, дерево / имя)

    куда = tmp_path_factory.mktemp("колесо")
    готово = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(куда), str(дерево)],
        capture_output=True, text=True)
    if готово.returncode != 0:
        if "No module named build" in готово.stderr:
            pytest.skip("нет `build`: pip install build")
        raise AssertionError(f"колесо не собралось:\n{готово.stderr[-2000:]}")
    колёса = list(куда.glob("*.whl"))
    assert len(колёса) == 1, f"ждали одно колесо, вышло {колёса}"
    return колёса[0]


def test_в_колесо_попала_таблица_типов(колесо):
    """Без неё пакет не ввозится: её читают классы полей при ввозе.

    Отдельной проверкой от установки, потому что называет причину. Установка
    скажет «не ввозится», а это -- чего именно не хватило.
    """
    import zipfile

    имена = zipfile.ZipFile(колесо).namelist()
    assert "oneframework/field-types.json" in имена, (
        "таблицы типов нет в колесе. Она едет `package-data` в pyproject.toml; "
        f"в колесе лежит: {sorted(и for и in имена if и.endswith('.json'))}")


def test_установленный_пакет_ввозится(колесо, tmp_path):
    """Поставить в чистое окружение и ввезти -- как это сделает человек.

    В чистое, а не в текущее: в текущем пакет уже стоит из дерева, и ввоз
    прошёл бы у него, ничего не доказав.
    """
    жильё = tmp_path / "venv"
    venv.create(жильё, with_pip=True)
    питон = жильё / ("Scripts" if sys.platform == "win32" else "bin") / "python"

    ставим = subprocess.run([str(питон), "-m", "pip", "install", "--quiet", str(колесо)],
                            capture_output=True, text=True)
    assert ставим.returncode == 0, f"установка не прошла:\n{ставим.stderr[-2000:]}"

    # Из `tmp_path`, а не из корня дерева: запустись оно там -- питон нашёл бы
    # пакет соседней папкой, и проверка мерила бы дерево, а не установку.
    проба = subprocess.run(
        [str(питон), "-c",
         "import json, oneframework;"
         " from oneframework.protocol import load;"
         " print(json.dumps(sorted(load()['types'])))"],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert проба.returncode == 0, (
        f"установленный пакет не ввозится:\n{проба.stderr[-2000:]}")

    # Не просто «ввёзся»: таблица обязана быть прочитанной и полной. Пустой
    # ответ означал бы, что файл нашёлся, а содержимое потерялось.
    типы = json.loads(проба.stdout)
    образец = json.loads((ROOT / "protocol" / "field-types.json").read_text(
        encoding="utf-8"))
    assert типы == sorted(образец["types"]), (
        f"установленный пакет знает не те типы: {типы}")
