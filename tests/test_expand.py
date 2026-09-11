"""Вид как документ -- со стороны **объявления**."""

import json

import pytest


from oneframework import (
    Accordion, App, Boolean, Button, Delete, List, Many2one,
    Menu, Model, Pill, Repeat, Row, String, Tab, Tabs, View,
)
from oneframework.errors import DslError
from oneframework.model.expr import Expr, Ref, Template, expr, item, iter_refs, parse_template
from oneframework.model.exprjson import from_json, to_json
from oneframework.ui.view import document

class Board(Model):
    name = String("Название")

class Task(Model):
    title = String("Задача")
    done = Boolean("Выполнено")
    board = Many2one(Board, "Список")

class TaskRow(View):
    model = Task

    def ui(self, record):
        return Row(record.title(), record.done(widget="checkbox"))

class Boards(View):
    _title = "Списки"

    def ui(self, record):
        return Tabs(
            Repeat(
                Board,
                Tab(
                    "{item.name}",
                    Pill(expr("count(Task, record.board = item.id & !record.done)")),
                    List(
                        Task,
                        item=TaskRow,
                        label="{item.name}",
                        domain=expr("record.board = item.id & !record.done"),
                        menu=Menu(
                            Button(
                                "Удалить выполненные",
                                action=Delete(
                                    Task,
                                    domain=expr("record.board = item.id & record.done"),
                                    confirm="Удалить всё выполненное в «{item.name}»?",
                                ),
                                enabled=expr("exists(Task, record.board = item.id & record.done)"),
                            ),
                        ),
                    ),
                    Accordion(
                        List(Task, item=TaskRow,
                             domain=expr("record.board = item.id & record.done")),
                        label="Выполненные",
                        visible=expr("exists(Task, record.board = item.id & record.done)"),
                    ),
                ),
            ),
        )

# ------------------------------------------------------------------ шаблоны
def test_a_plain_string_stays_a_plain_string():
    assert parse_template("Выполненные") == "Выполненные"

def test_a_reference_makes_it_a_template():
    tmpl = parse_template("Удалить «{item.name}»?")
    assert isinstance(tmpl, Template)
    assert to_json(tmpl) == {"fmt": ["Удалить «", {"i": "name"}, "»?"]}

def test_a_template_survives_json():
    tmpl = parse_template("{item.name}: осталось")
    assert to_json(from_json(json.loads(json.dumps(to_json(tmpl))))) == to_json(tmpl)

def test_other_scopes_say_so_rather_than_printing_braces():
    with pytest.raises(DslError) as excinfo:
        parse_template("Удалить «{record.name}»?")
    assert "record.name" in str(excinfo.value)

# ----------------------------------------------------------------- документ
def test_the_document_needs_neither_a_frame_nor_a_record():
    doc = document(Boards)
    assert doc["type"] == "view" and doc["name"] == "Boards"
    assert json.dumps(doc)                      # едет по проводу как есть

def test_the_document_keeps_the_repeat_rather_than_its_result():
    repeat = document(Boards)["children"][0]["children"][0]
    assert repeat["type"] == "repeat" and repeat["model"] == "Board"

def test_the_document_keeps_names_as_references():
    tab = document(Boards)["children"][0]["children"][0]["children"][0]
    assert tab["label"] == {"fmt": [{"i": "name"}]}

def _пакетом(app, seed=None):
    """Приложение -> пакет объявления: дорога в план теперь одна."""
    from oneframework.declaration import Bundle, declare

    return Bundle(declare(app, seed))
