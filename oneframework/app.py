"""``App`` -- the object a user's ``app.py`` ends with."""

from __future__ import annotations

import re
import sys

from .errors import DslError, OneFrameworkError, did_you_mean
from .model.fields import Many2one
from .model.meta import Model, ModelMeta
from .ui.view import View, ViewMeta
from .model.ids import seeded_ids

__all__ = ["App"]

def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return slug or "app"

class App:
    """Entry point: ``app = App(Todo)``."""
    def __init__(self, *screens, title=None, db_name=None,
                 color="#6750A4", dynamic_color=False, locale=None, theme="auto", modules=None,
                 sync=None, python_packages=None, logic=None):
        from .ui.screen import Screen

        self.modules = list(modules or [])

        #: Логика, объявленная **самим приложением**, а не модулем.
        self.logic = list(logic or [])

        #: Питоновские пакеты, которым место **на устройстве**: то, что в SQL
        #: не переводится -- словарная морфология, разбор чужого формата.
        self.python_packages = list(python_packages or [])

        self.screens = []
        for item in screens:
            if isinstance(item, Screen):
                self.screens.append(item)
            elif isinstance(item, type) and issubclass(item, View):
                self.screens.append(Screen(item))
            else:
                raise DslError(
                    f"App(...) expects View classes or Screen(...), got {item!r}."
                )
        if not self.screens and self.modules:
            self.screens = _screens_from_modules(self.modules)
        if not self.screens:
            raise DslError(
                "App(...) needs at least one screen: App(MyView) or "
                "App(Screen(MyView, label='...'), ...)."
            )
        self.screens.sort(key=lambda s: s.sequence)

        root_view = self.screens[0].view
        self.root_view = root_view
        self.title = title or getattr(root_view, "_title", root_view.__name__)
        self.db_name = db_name or f"{_slug(self.title)}.db"
        #: Material 3 seed colour -- the renderer derives the whole tonal
        #: palette (light and dark) from it.
        self.color = color
        #: UI-chrome language; ``None`` means follow the device.
        self.locale = locale
        #: Брать ли цвет у системы вместо объявленного.
        self.dynamic_color = bool(dynamic_color)

        #: Framework7 theme: "auto" (Material 3 everywhere, the iOS look on
        #: Apple devices), or pin one with "md" / "ios".
        self.theme = theme
        self.sync = sync

        packages = _source_packages(self.modules, self.screens)
        self.models = _models_in(packages)
        #: Every View the app declares -- what `oneframework check` walks.
        self.views = _defined_in(packages, ViewMeta)

    # -- lookups -----------------------------------------------------------
    def model_by_name(self, name):
        for m in self.models:
            if m.__name__ == name:
                return m
        raise OneFrameworkError(
            f"Unknown model {name!r}." + did_you_mean(name, [m.__name__ for m in self.models])
        )

    # -- metadata for the renderer ----------------------------------------
    def meta(self):
        return {
            "title": self.title,
            "root": self.root_view.__name__,
            "screens": [s.ir() for s in self.screens],
            "color": self.color,
            "locale": self.locale,
            "theme": self.theme,
            "sync": self.sync,
            "models": {
                m.__name__: {
                    "label": m._label,
                    "table": m._table,
                    "display_field": (m.display_field().name if m.display_field() else None),
                    "fields": {
                        name: {
                            "type": f.ftype,
                            "label": f.display_label,
                            "required": bool(f.required),
                            "widgets": list(f.widgets),
                            "default_widget": f.default_widget,
                            "comodel": (
                                f.resolve_comodel().__name__ if isinstance(f, Many2one) else None
                            ),
                        }
                        for name, f in m._fields.items()
                    },
                }
                for m in self.models
            },
        }

    # -- lifecycle ---------------------------------------------------------

    #: ``start()`` поднимал питоновский рантайм.

    # -- бизнес-логика в WASM ---------------------------------------------
    def logic_modules(self):
        out = []
        for model in self.models:
            actions = [a.declaration() for a in getattr(model, "_actions", ())]
            if actions:
                out.append({"actions": actions})
        out += list(self.logic)
        for module in self.modules:
            out.extend(module.logic)
        return out

    #: ``attach_logic()`` поднимал питоновский хост логики.

    def _seeded_before(self, db, name):
        if name != "app":
            return False
        return bool(db.get_meta(f"seeded:{_slug(self.title)}") or db.get_meta("seeded"))

    def _seeds(self, explicit=None):
        """``(name, fn)`` for every seed to consider, modules first."""
        out = [(m.name, m.seed) for m in self.modules if m.seed]
        if explicit is not None:
            out.append(("app", explicit))
        return out

    def static_files(self, suffix=".js"):
        files = []
        for module in self.modules:
            files.extend(module.static_files(suffix))
        return files

    def __repr__(self):
        modules = f" modules={[m.name for m in self.modules]}" if self.modules else ""
        return f"<App {self.title!r} root={self.root_view.__name__}{modules}>"

def _source_packages(modules, screens):
    if modules:
        return {m.name for m in modules}
    # A single-file app: `app.py` holds the models and the views alike.
    return {(s.view.__module__ or "").split(".")[0] for s in screens}

def _defined_in(packages, meta):
    base = {ModelMeta: Model, ViewMeta: View}[meta]
    seen, order = set(), []
    for name, module in sorted(sys.modules.items()):
        if module is None or name.split(".")[0] not in packages:
            continue
        for value in vars(module).values():
            if (
                isinstance(value, meta)
                and value is not base
                and value not in seen
                and (value.__module__ or "").split(".")[0] in packages
            ):
                seen.add(value)
                order.append(value)
    return order

def _models_in(packages):
    seen, order = set(), []

    def add(model):
        if model is None or model in seen:
            return
        seen.add(model)
        order.append(model)
        # A relation may cross into a package this app did not name -- a shared
        # library of lookup tables.
        for rel in model.relations():
            add(rel.resolve_comodel())

    for model in _defined_in(packages, ModelMeta):
        add(model)
    return order

def _screens_from_modules(modules):
    from .ui.screen import Screen

    found = []
    for module in modules:
        screen = getattr(module.package, "SCREEN", None)
        if screen is not None:
            if not isinstance(screen, Screen):
                raise DslError(
                    f"Module {module.name!r}: SCREEN must be a Screen(...), "
                    f"got {screen!r}."
                )
            found.append(screen)
            continue
        root = getattr(module.package, "ROOT", None)
        if root is not None:
            found.append(Screen(root, label=module.name.replace("_", " ").capitalize()))
    if not found:
        raise DslError(
            "No module declares SCREEN. Add "
            "'SCREEN = Screen(MyView, label=\'...\', icon=\'...\')' to a module's "
            "__init__.py so the app knows what to show."
        )
    return found

#: ``publish`` раскладывал приложение по базе.
