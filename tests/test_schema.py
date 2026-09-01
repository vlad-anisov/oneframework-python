"""Модель как данные: документ схемы обязан нести всё, что нужно чужому бэкенду.

Проверяется не форма ради формы, а то, без чего вторая реализация не поедет:
типы, связи с ondelete, автополя и переносимость через JSON.
"""

import json

from oneframework import Boolean, Date, Many2one, Model, String, Text
from oneframework.model.schema import field_schema, model_schema, type_schema


class Board(Model):
    name = String("Название", required=True)


class Task(Model):
    title = String("Задача", required=True)
    details = Text("Детали")
    done = Boolean("Выполнено")
    deadline = Date("Срок")
    board = Many2one(Board, "Список", ondelete="cascade")


def _by_name(model):
    return {f["name"]: f for f in model_schema(model)["fields"]}


def test_auto_fields_are_present():
    """id/created_at/updated_at -- настоящие колонки, чужой бэкенд их обязан знать."""
    assert {"id", "created_at", "updated_at"} <= set(_by_name(Task))


def test_relation_carries_target_and_ondelete():
    board = _by_name(Task)["board"]
    assert board["ftype"] == "many2one"
    assert board["comodel"] == "Board"      # имя, а не объект класса
    assert board["ondelete"] == "cascade"


def test_required_and_label_survive():
    title = _by_name(Task)["title"]
    assert title["required"] is True
    assert title["label"] == "Задача"
    assert "required" not in _by_name(Task)["done"]   # ложь не шумит


def test_widget_only_when_it_differs_from_the_type():
    fields = _by_name(Task)
    assert fields["details"]["widget"] == "textarea"
    assert "widget" not in fields["title"]           # у типа он и так такой


def test_widget_list_lives_on_the_type_not_the_field():
    types = type_schema([Board, Task])
    assert "textarea" in types["string"]["widgets"]
    assert types["many2one"]["sql"] == "TEXT"
    for f in model_schema(Task)["fields"]:
        assert "widgets" not in f


def test_document_survives_json():
    doc = {"types": type_schema([Board, Task]),
           "models": [model_schema(Board), model_schema(Task)]}
    assert json.loads(json.dumps(doc, ensure_ascii=False)) == doc
