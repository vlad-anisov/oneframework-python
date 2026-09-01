"""``Screen`` -- one top-level destination of an application.

An app is a list of screens. How they are *shown* is not part of the DSL: on a
phone they become a bottom navigation bar, on a wider window a permanent side
panel. That follows what both platforms now recommend -- Material 3 replaced
its navigation drawer with a rail that expands with the window, and iPadOS 18
made the tab bar and the sidebar two presentations of the same thing.

So there is no ``Panel`` and no navigation ``Tabs`` in the DSL: describing the
structure is the app's job, choosing the chrome is the renderer's.
"""

from __future__ import annotations

from ..errors import DslError

__all__ = ["Screen"]


class Screen:
    """A destination: one root View plus how to label it in navigation."""

    _counter = 0

    def __init__(self, view, label=None, icon=None, sequence=None):
        from .view import View

        if not (isinstance(view, type) and issubclass(view, View)):
            raise DslError(f"Screen(...) expects a View class, got {view!r}.")
        self.view = view
        self.label = label or getattr(view, "_title", view.__name__)
        self.icon = icon
        Screen._counter += 1
        #: navigation order; declaration order when not given
        self.sequence = Screen._counter * 10 if sequence is None else sequence

    @property
    def key(self):
        return self.view.__name__

    def master_detail(self):
        """Открытая запись становится рядом со списком или вместо него?

        Рядом, если окно достаточно широкое, -- так делают обе платформы на
        планшете. Исключение -- список, попросивший быть таблицей: таблице нужна
        вся ширина, и запись открывается целой страницей.

        **Решает это устройство, а не объявление**, и потому здесь всегда
        ``True``. Ответ читается с нарисованного дерева -- единственного места,
        где дерево вообще существует, -- а рисует его рантайм. До 21.08.2026
        рантайм был питоновским и стоял в том же процессе, так что метод мог
        спросить его через ``sys.modules``. Теперь он на устройстве, и настоящий
        ответ даёт `Runtime._masterDetail` в `libs/js/src/core/runtime/session.js`; он же
        едет в снимке, и проверяется по снимку
        (`test_screens.py::test_a_table_screen_opts_out_of_the_split`).

        Оставлено значением, а не убрано: ``meta()`` описывает объявление, и
        поле в нём должно быть -- сборка кладёт его в манифест до того, как
        появится хоть один нарисованный экран.
        """
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
