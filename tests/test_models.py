"""Model metadata, auto fields, defaults, relations and CRUD."""

import pytest

from oneframework import Boolean, Color, Integer, Many2one, Model, String, View
from oneframework.errors import DslError


class Category(Model):
    name = String("Name", required=True)
    color = Color("Color")


class Item(Model):
    title = String("Title", required=True)
    notes = String("Notes")
    category = Many2one(Category, "Category")
    done = Boolean("Done")
    position = Integer()


def test_auto_fields_are_added_without_being_declared():
    for auto in ("id", "hlc", "created_at", "updated_at"):
        assert auto in Item._fields, auto
    assert Item._fields["created_at"].ftype == "datetime"
    # The key is what makes a record referable across devices; two calls to
    # its default must never agree.
    make = Item._fields["id"].default
    assert make() != make()
    # ...and it still sorts by the moment it was made, so `ORDER BY id` keeps
    # meaning "in the order they were added" now that the counter is gone.
    keys = [make() for _ in range(50)]
    assert keys == sorted(keys)


def test_declared_field_order_is_preserved():
    auto = ("id", "hlc", "created_at", "updated_at")
    declared = [n for n in Item._fields if n not in auto]
    assert declared == ["title", "notes", "category", "done", "position"]


def test_table_name_is_snake_cased():
    assert Item._table == "item"

    class TodoLineThing(Model):
        name = String()

    assert TodoLineThing._table == "todo_line_thing"


def test_boolean_defaults_to_false_without_an_explicit_default():
    assert Item._fields["done"].default() is False
    assert Item._fields["position"].default() == 0


def test_many2one_uses_an_id_column_and_resolves_its_comodel():
    field = Item._fields["category"]
    assert field.column == "category_id"
    assert field.resolve_comodel() is Category


def test_display_field_prefers_name():
    assert Category.display_field().name == "name"
    assert Item.display_field().name == "title"


def test_unknown_field_error_suggests_a_correction():
    with pytest.raises(DslError) as excinfo:
        Item.field("titel")
    assert "titel" in str(excinfo.value)
    assert "title" in str(excinfo.value)


# --------------------------------------------------------------------- CRUD










# ---------------------------------------------------------------- View state


#: Здесь стояли шесть проверок на **питоновской** базе: обход CRUD, цвет,
#: обнуление ссылки при удалении, добавление колонки, вторая выкладка схемы без
#: DDL, поля вида без колонок. Каркас этой базы больше не зовёт.
#:
#: Что переехало на живую сторону (`tests/test_js_storage.py`) и закрыто
#: мутациями: обнуление ссылки и вторая выкладка схемы без DDL -- обе были
#: беззащитны, снятые правила оставляли 690 и 703 зелёных проверки.
#:
#: Что уже сторожилось и повторять незачем: обход CRUD (его делает каждая
#: проверка рантайма через хост), перекладка таблицы (снятая роняет 42 проверки
#: и 104 подъёма), типы полей (`test_js_fields_parity`).
