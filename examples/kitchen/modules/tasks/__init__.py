"""Tasks: the list section, and the module that ships a custom JS widget."""

from oneframework import Screen

from .models import Label, Person, Task
from .views import Board, TaskDetail, TaskItem

__all__ = ["Label", "Person", "Task", "Board", "TaskDetail", "TaskItem"]

SCREEN = Screen(Board, label="Задачи", icon="check", sequence=10)
