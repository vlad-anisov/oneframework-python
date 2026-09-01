"""Repeat, Count и Exists -- то, чем заменяется питоновский цикл в виде.

Проверяется главное свойство: структура следует за данными, а не за моментом,
когда собиралось дерево. Плюс то, что опечатка в ``item.`` падает при сборке --
иначе она нарисует пустую вкладку и промолчит.
"""

import json

import pytest

from oneframework import Boolean, Count, Exists, Many2one, Model, Repeat, Row, String
from oneframework.errors import DslError
from oneframework.model.exprjson import from_json, to_json
from oneframework.model.expr import item, record


class Board(Model):
    name = String("Название")


class Task(Model):
    title = String("Задача")
    done = Boolean("Выполнено")
    board = Many2one(Board, "Список")


def _built(node, model=Task):
    """Привязать к модели, как это делает build_ui, и выдать документ."""
    node.bind(model, "TestView")
    return node.ir()


def test_repeat_emits_its_model_and_body():
    ir = _built(Repeat(Board, Row(record.title())))
    assert ir["type"] == "repeat"
    assert ir["model"] == "Board"
    assert len(ir["children"]) == 1


def test_repeat_carries_its_own_domain():
    assert "domain" in _built(Repeat(Board, Row(), domain=record.name != ""))


def test_repeat_without_domain_says_nothing():
    assert "domain" not in _built(Repeat(Board, Row()))


def test_unknown_item_field_fails_at_build_time():
    """item.nmae вместо item.name -- ошибка сборки, а не пустой экран."""
    node = Repeat(Board, Row(record.title(visible=item.nmae)))
    with pytest.raises(DslError) as e:
        node.bind(Task, "TestView")
    assert "item.nmae" in str(e.value)
    assert "name" in str(e.value)          # подсказка про похожее поле


def test_known_item_field_passes():
    node = Repeat(Board, Row(record.title(visible=item.name)))
    node.bind(Task, "TestView")             # не должно бросить


def test_count_and_exists_survive_json():
    for expr in (Count(Task, (record.board == item.id) & ~record.done),
                 Exists(Task, record.done),
                 Count(Task)):
        back = from_json(json.loads(json.dumps(to_json(expr))))
        assert to_json(back) == to_json(expr)


def test_aggregate_names_its_model_not_the_class_object():
    doc = to_json(Count(Task, record.done))
    assert doc == {"agg": "count", "model": "Task", "domain": {"r": "done"}}
    assert json.dumps(doc)                  # сериализуемо без обхода


def test_bare_count_has_no_domain_key():
    assert "domain" not in to_json(Count(Task))
