"""Tasks: depends on contacts, because a task has an assignee."""

from oneframework import Screen

from .models import Task
from .views import Board

__all__ = ["Task", "Board"]

#: loaded first, because a task has an assignee
DEPENDS = ("contacts",)

SCREEN = Screen(Board, label="Задачи", icon="check")
