"""Определения живут в базе рядом с данными.

Проверяется то, ради чего это сделано: у определения есть отпечаток, ревизия
растёт только при настоящем изменении, и сверка по отпечаткам отвечает на
единственный вопрос доставки — «что у нас новее».
"""

import pytest

from oneframework import App, Boolean, List, Many2one, Model, String, View
from oneframework.model import defs


class Board(Model):
    name = String("Название")


class Task(Model):
    title = String("Задача")
    done = Boolean("Выполнено")
    board = Many2one(Board, "Список")


class Screen(View):
    _title = "Экран"

    def ui(self, record):
        return List(Task)


@pytest.fixture
def db():
    d = Database(MemoryStorage())
    d.ensure_schema([Board, Task])
    return d


















def test_an_app_puts_its_models_into_the_plan():
    """Выкладка обязана назвать все модели приложения, и без просьбы.

    Спрашивается план, а не база: класть его в базу -- работа сборщика на JS
    (`libs/js/src/build-db.mjs`), и она проверяется в `test_build_db.py`.
    """
    from oneframework.cli.plan import build_plan

    план = build_plan(_пакетом(App(Screen, title="T")))
    assert {и for в, и, _ in план["defs"] if в == "model"} == {"Board", "Task"}


#: Здесь стояли проверки питоновского писателя определений: отпечаток, ревизия,
#: «что вам не доехало», отказ на чужом виде. Каркас этого писателя больше не
#: зовёт -- базу пишет сборщик на JS, -- и живая половина правил оказалась
#: беззащитной: снятый рост ревизии оставлял всю сюиту зелёной. Правила
#: переехали туда, где они и работают: `tests/test_js_defs.py`.


def _пакетом(app, seed=None):
    """Приложение -> пакет объявления: дорога в план теперь одна.

    Своей проверки здесь нет -- что пакет несёт всё, стережёт
    `test_plan_one_road.py`. Здесь только перевод.
    """
    from oneframework.declaration import Bundle, declare

    return Bundle(declare(app, seed))
