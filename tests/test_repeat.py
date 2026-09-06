"""Repeat и свёртки -- то, чем заменяется питоновский цикл в виде."""

import json

import pytest

from oneframework import Boolean, Many2one, Model, Repeat, Row, String
from oneframework.errors import DslError
from oneframework.model.exprjson import from_json, to_json
from oneframework.model.expr import expr, item, record

class Board(Model):
    name = String("Название")

class Task(Model):
    title = String("Задача")
    done = Boolean("Выполнено")
    board = Many2one(Board, "Список")

def _built(node, model=Task):
    node.bind(model, "TestView")
    return node.ir()

def test_repeat_emits_its_model_and_body():
    ir = _built(Repeat(Board, Row(record.title())))
    assert ir["type"] == "repeat"
    assert ir["model"] == "Board"
    assert len(ir["children"]) == 1

def test_repeat_carries_its_own_domain():
    assert "domain" in _built(Repeat(Board, Row(), domain=expr('record.name != ""')))

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

def test_свёртка_доезжает_объявлением():
    doc = to_json(expr("count(Task, record.done, via=board)"))
    assert doc == {"text": "count(Task, record.done, via=board)"}
    assert json.dumps(doc)                  # сериализуемо без обхода
