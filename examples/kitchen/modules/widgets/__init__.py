"""Widgets: every field type and every widget it offers."""

from oneframework import Screen

from .models import Sample
from .views import SampleDetail, SampleItem, Widgets

__all__ = ["Sample", "SampleDetail", "SampleItem", "Widgets"]

#: loaded after tasks, for `selection:pill` -- the widget that module ships
DEPENDS = ("tasks",)

SCREEN = Screen(Widgets, label="Виджеты", icon="palette", sequence=40)
