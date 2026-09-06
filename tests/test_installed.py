"""Пакет обязан работать там, где его поставят, а не только в дереве."""

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

#: Что нужно, чтобы собрать колесо.
ДЛЯ_СБОРКИ = ("pyproject.toml", "oneframework", "README.md", "LICENSE")

@pytest.fixture(scope="module")
def колесо(tmp_path_factory):
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
    """Без неё пакет не ввозится: её читают классы полей при ввозе."""
    import zipfile

    имена = zipfile.ZipFile(колесо).namelist()
    assert "oneframework/field-types.json" in имена, (
        "таблицы типов нет в колесе. Она едет `package-data` в pyproject.toml; "
        f"в колесе лежит: {sorted(и for и in имена if и.endswith('.json'))}")

def test_установленный_пакет_ввозится(колесо, tmp_path):
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

    # Не просто «ввёзся»: таблица обязана быть прочитанной и полной.
    типы = json.loads(проба.stdout)
    образец = json.loads((ROOT / "protocol" / "field-types.json").read_text(
        encoding="utf-8"))
    assert типы == sorted(образец["types"]), (
        f"установленный пакет знает не те типы: {типы}")
