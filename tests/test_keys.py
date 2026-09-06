"""Ключ записи и отметка порядка -- то, что меняется до всякого обмена."""

from __future__ import annotations

from oneframework import Boolean, Integer, Many2many, Many2one, Model, String

class Tag(Model):
    _label = "Метка"
    name = String("Метка")

class Board(Model):
    _label = "Список"
    name = String("Название", required=True)

class Task(Model):
    _label = "Задача"
    title = String("Задача", required=True)
    done = Boolean("Выполнено")
    sequence = Integer()
    board = Many2one(Board, "Список")
    tags = Many2many(Tag, "Метки")

MODELS = [Tag, Board, Task]

# --- внешний порядок ---------------------------------------------------------


#: Здесь стояли две проверки питоновских часов: отставшие подтягиваются чужой
#: отметкой, перезапущенные не начинают сначала.
