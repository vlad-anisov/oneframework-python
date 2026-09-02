"""Питоновские двери в сборку базы.

Что база выходит правильной, проверяет `tests/js/build-db.test.mjs` -- там
сборщик и живёт. Здесь остались двери, которыми в него ходит питон:
`write_app_db`, `build_plan` и загрузка приложения, объявленного не на питоне.

Сегодня пишет один. Питон говорит, что класть (`cli/plan.py`), кладёт
`libs/js/src/build-db.mjs`.

Пока питоновский писатель был в дереве, здесь стояла сверка двух баз побайтно.
Она своё отработала -- переезд был сделан под ней, и два расхождения (пустая
таблица логики, связи многие-ко-многим) поймала именно она. Питоновского
писателя не стало, и сверять больше не с чем: остались правила, записанные
прямо.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from conftest import needs_node
from oneframework import App, Model, Screen, String, View

ROOT = Path(__file__).resolve().parents[1]
СБОРЩИК = ROOT / "libs" / "js" / "src" / "build-db.mjs"

pytestmark = needs_node


#: Каждый пример строится **отдельным процессом**, и это не осторожность.
#: Реестр моделей глобален и ключуется именем класса, а посев примера ввозит
#: свой ``app`` по-настоящему: загрузи два примера в один процесс -- и посев
#: запишет строки в классы соседа, причём молча. Тот же довод записан в
#: ``test_document.py`` и в ``App._defined_in``.
def _содержимое(файл):
    """Что в базе: форма таблиц, определения, записи и мета."""
    import sqlite3

    con = sqlite3.connect(файл)
    con.row_factory = sqlite3.Row
    таблицы = [(r["name"], r["sql"]) for r in con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")]
    определения = [dict(r) for r in con.execute(
        'SELECT "kind","name","fingerprint","doc","revision" FROM "_oneframework_def" '
        'ORDER BY "kind","name"')]
    мета = {r["key"]: r["value"] for r in con.execute(
        'SELECT "key","value" FROM "_oneframework_meta"')}
    записи = {}
    for имя, _ in таблицы:
        if имя.startswith("_oneframework") or имя.startswith("sqlite"):
            continue
        строки = [dict(r) for r in con.execute(f'SELECT * FROM "{имя}" ORDER BY "id"')]
        #: Отметка часов -- **не** сравнивается: она несёт время и номер узла,
        #: и они разные у двух писателей по определению. Всё остальное в строке
        #: обязано совпасть.
        for с in строки:
            с.pop("hlc", None)
            с.pop("created_at", None)
            с.pop("updated_at", None)
        записи[имя] = строки
    con.close()
    return {"таблицы": таблицы, "определения": определения, "мета": мета, "записи": записи}


#: Пакет объявления -- вторая дорога в приложение: `.mjs`, `.kt`, `.json`.
#: У неё нет ни питоновских классов, ни посева, и прежде она шла мимо
#: сборщика -- со своей, третьей записью правила создания таблиц. Теперь она
#: идёт тем же планом, и проверять её надо отдельно: сборка примера на JS
#: сломалась ровно на этом переезде, и поймал это не прогон, а руки.
def test_a_declaration_bundle_builds_through_the_same_writer(tmp_path):
    """Приложение, объявленное **не на питоне**, собирается тем же сборщиком."""
    from oneframework.cli.assets import write_app_db
    from oneframework.cli.sources import load

    app = load(ROOT / "examples" / "notes-js" / "app.mjs")
    файл = tmp_path / "bundle.db"
    write_app_db(app, None, файл)

    что = _содержимое(файл)
    таблицы = {имя for имя, _ in что["таблицы"]}
    assert "_oneframework_def" in таблицы, "определений в базе нет"
    assert any(not и.startswith(("_oneframework", "sqlite")) for и in таблицы), (
        f"таблиц самого приложения нет: {sorted(таблицы)}")
    виды = {d["name"] for d in что["определения"] if d["kind"] == "view"}
    assert виды, "ни одного вида не выложено"


def test_a_plan_refuses_a_seed_by_name(tmp_path):
    """Посев в план стороной больше не заходит: он записан в пакете.

    Прежде пакет посева не нёс, и `build_plan` отказывал ему вслух. Тогда
    посев прогоняла сборка -- и собрать то же приложение без питона было нельзя.
    Теперь строки пишет тот, кто печатает пакет (`declare(app, seed)`), а
    `build_plan` не принимает их ни от кого.

    Отказ, а не молчание: проглоти план `seed=`, база вышла бы без демо-данных,
    и объяснить это было бы нечем -- ни ошибки, ни следа, просто нет записей.
    """
    from oneframework.cli.plan import build_plan
    from oneframework.cli.sources import load
    from oneframework.errors import OneFrameworkError

    app = load(ROOT / "examples" / "notes-js" / "app.mjs")
    with pytest.raises(OneFrameworkError, match="declare"):
        build_plan(app, seed=lambda _db: None)


def test_a_javascript_bundle_declares_it_has_no_seeds(tmp_path):
    """Пустой раздел -- законный ответ, отсутствие раздела -- потеря.

    Привязка на JavaScript демо-данных не знает, и печатает `"seeds": []`. Если
    бы ключа просто не было, «данных нет» и «раздел потеряли» стали бы
    неразличимы -- ровно тем же доводом, что у «logic».
    """
    from oneframework.cli.plan import build_plan
    from oneframework.cli.sources import load

    app = load(ROOT / "examples" / "notes-js" / "app.mjs")
    assert app.seeds == []
    assert build_plan(app)["seeds"] == []


# --------------------------------------------------------------------- посев
#: Посев -- единственное место выкладки, у которого есть память: он смотрит на
#: отметку и решает, сеять ли. Проверяется он **на новой дороге**, потому что
#: старая (`App.publish`) уходит, а правила остаются те же.
def _посеять(tmp_path, app, seed, файл=None, поверх=False):
    from oneframework.cli.assets import write_app_db

    файл = файл or (tmp_path / "seeded.db")
    write_app_db(app, seed, файл, поверх=поверх)
    return файл


def _строк(файл, таблица):
    import sqlite3

    con = sqlite3.connect(файл)
    try:
        return con.execute(f'SELECT count(*) FROM "{таблица}"').fetchone()[0]
    finally:
        con.close()


def _мета(файл, ключ, значение):
    import sqlite3

    con = sqlite3.connect(файл)
    try:
        con.execute('INSERT OR REPLACE INTO "_oneframework_meta" ("key","value") '
                    "VALUES (?,?)", (ключ, значение))
        con.commit()
    finally:
        con.close()


#: Модель и вид -- на уровне модуля: выкладка ищет классы в пространстве имён
#: модуля (`_defined_in`), и заведённые в теле проверки туда не попадают --
#: приложение уехало бы к сборщику пустым.
class Заметка(Model):
    _table = "note_seeded"
    name = String("Имя")


class Дом(View):
    def ui(self, record):
        return ()


def _посев(db):
    db.create(Заметка, {"name": "раз"})


@pytest.fixture()
def посеянное():
    """Крошечное приложение с посевом -- ровно чтобы считать строки."""
    return App(Screen(Дом), title="Seeded"), _посев, "note_seeded"


def test_a_seed_runs_once_even_when_the_build_is_repeated(tmp_path, посеянное):
    """Вторая сборка поверх той же базы не сеет заново.

    Иначе демо-данные удваивались бы при каждом обновлении -- молча, потому что
    вставка проходит и ошибки не даёт.
    """
    app, seed, таблица = посеянное
    файл = _посеять(tmp_path, app, seed)
    assert _строк(файл, таблица) == 1
    # Поверх существующей: так ходит `inspect --db` и так же выглядит
    # обновление приложения на устройстве.
    _посеять(tmp_path, app, seed, файл, поверх=True)
    assert _строк(файл, таблица) == 1


def test_a_marker_from_an_older_framework_is_adopted(tmp_path, посеянное):
    """Отметку прежней схемы имени сборка обязана принять, а не сеять заново.

    Отметки были сперва общими на приложение, потом по-модульными. Установленное
    приложение не должно удваивать демо-данные оттого, что каркас переименовал
    отметку. Правило пережило переезд выкладки на JS -- сначала не пережило, и
    поймано было не прогоном, а разбором: старая проверка стояла на старой
    дороге и новую не трогала вовсе.
    """
    app, seed, таблица = посеянное
    файл = tmp_path / "legacy.db"
    # База, где приложение уже посеяно **старой** отметкой и ни одной строки
    # нового посева нет: сборка обязана оставить её пустой.
    _посеять(tmp_path, app, None, файл)
    _мета(файл, "seeded:seeded", "1")
    _посеять(tmp_path, app, seed, файл, поверх=True)
    assert _строк(файл, таблица) == 0, "старая отметка не принята -- посев прошёл заново"


def test_building_a_second_app_does_not_inherit_the_first(tmp_path):
    """Сборка начинает с чистого файла, а не ложится поверх предыдущей.

    Собранные подряд два примера копили друг друга: определения обоих в одной
    базе, двадцать моделей вместо двух. Ошибка молчаливая -- сборка проходит,
    файл растёт, -- и замечает её первый же запуск приложения, у которого вдруг
    чужие экраны.

    Поймано было прогоном e2e, а не этой проверкой: она всегда собирала в свежий
    временный файл и потому не могла столкнуться с накоплением.
    """
    from oneframework.cli.assets import write_app_db
    from oneframework.cli.sources import load

    файл = tmp_path / "shared.db"
    write_app_db(load(ROOT / "examples" / "todo" / "app.py"), None, файл)
    первое = {о["name"] for о in _содержимое(файл)["определения"] if о["kind"] == "model"}

    write_app_db(load(ROOT / "examples" / "gtasks" / "app.py"), None, файл)
    второе = {о["name"] for о in _содержимое(файл)["определения"] if о["kind"] == "model"}

    assert первое & второе == set() or первое != второе
    assert not (первое - второе) & второе, "модели первого приложения остались"
    assert первое - второе == первое, f"вторая сборка унаследовала {первое & второе}"


def test_inspect_keeps_what_is_already_in_the_file(tmp_path):
    """А `inspect --db` наоборот: он обязан открыть базу пользователя, не стереть.

    Обратная сторона умолчания выше. Перепутай их -- и команда осмотра стирала
    бы данные, которые пришла показать.
    """
    import sqlite3

    from oneframework.cli.assets import write_app_db
    from oneframework.cli.sources import load

    файл = tmp_path / "user.db"
    app = load(ROOT / "examples" / "todo" / "app.py")
    write_app_db(app, None, файл)

    con = sqlite3.connect(файл)
    con.execute('INSERT INTO "todo_line" ("id","text") VALUES (?,?)', ("u-1", "моя"))
    con.commit()
    con.close()

    write_app_db(app, None, файл, поверх=True)
    con = sqlite3.connect(файл)
    try:
        assert con.execute('SELECT count(*) FROM "todo_line" WHERE "id" = ?',
                           ("u-1",)).fetchone()[0] == 1, "запись пользователя стёрта"
    finally:
        con.close()
