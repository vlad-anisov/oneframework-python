"""``Screen`` -- one top-level destination of an application."""

from __future__ import annotations

from ..errors import DslError

__all__ = ["Screen"]

class Screen:
    _counter = 0

    def __init__(self, view, label=None, icon=None, sequence=None):
        from .view import View

        if not (isinstance(view, type) and issubclass(view, View)):
            raise DslError(f"Screen(...) expects a View class, got {view!r}.")
        self.view = view
        self.label = label or getattr(view, "_title", view.__name__)
        self.icon = icon
        Screen._counter += 1
        self.sequence = Screen._counter * 10 if sequence is None else sequence

    @property
    def key(self):
        return self.view.__name__

    def master_detail(self):
        """Открытая запись становится рядом со списком или вместо него?"""
        return True

    def ir(self):
        return {
            "key": self.key,
            "label": self.label,
            "icon": self.icon,
            "view": self.view.__name__,
            "master_detail": self.master_detail(),
        }

    def __repr__(self):
        return f"<Screen {self.key} {self.label!r}>"
