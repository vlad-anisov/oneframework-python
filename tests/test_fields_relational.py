"""One2many and Many2many at the storage layer."""

import pytest

from oneframework import (
    One2one,
    Integer,
    Many2many,
    Many2one,
    Model,
    One2many,
    String,
)
from oneframework.errors import DslError


class Passport(Model):
    number = String("Number", required=True)


class Skill(Model):
    name = String("Skill", required=True)


class Person(Model):
    name = String("Name", required=True)
    passport = One2one(Passport, "Passport")
    skills = Many2many(Skill, "Skills")
    age = Integer("Age")


class Note(Model):
    body = String("Body")
    person = Many2one(Person, "Person")


class PersonWithNotes(Model):
    _table = "person_with_notes"
    name = String("Name")


MODELS = [Passport, Skill, Person, Note]


# ------------------------------------------------------------------ One2one






def test_one2one_defaults_to_cascade():
    assert Person._fields["passport"].ondelete == "cascade"


# ----------------------------------------------------------------- One2many




def test_one2many_with_a_bad_inverse_is_a_clear_error():
    class Owner3(Model):
        notes = One2many(Note, "persn", "Notes")

    with pytest.raises(DslError) as excinfo:
        Owner3._fields["notes"].inverse_field()
    assert "persn" in str(excinfo.value) and "person" in str(excinfo.value)


# ---------------------------------------------------------------- Many2many


#: Здесь стояли восемь проверок, мерявших связи через **питоновскую** базу:
#: уникальный индекс у один-к-одному, чтение потомков, таблица связи, её
#: наполнение и очистка. Каркас этой базы больше не зовёт, а живая половина
#: правил была беззащитна -- сломанный `readOne2many` и снятый уникальный
#: индекс оставляли всю сюиту зелёной (проверено мутациями).
#:
#: Правила переехали в `tests/test_js_storage.py`, к той базе, которая на
#: устройстве и работает. Здесь осталось то, что про **объявление**: умолчание
#: `ondelete` и отказ на неверном обратном поле -- им база не нужна.
