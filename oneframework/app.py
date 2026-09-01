"""``App`` -- the object a user's ``app.py`` ends with.

It holds no UI logic of its own: it collects the destinations, works out which
models need a table, and can hand a :class:`Runtime` to a host (воркер браузера,
test harness, future native shell). The UI itself is not its business -- every
tree is built by the screen that draws it.
"""

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
    """Filesystem-safe identifier derived from an app title."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return slug or "app"


class App:
    """Entry point: ``app = App(Todo)``."""

    def __init__(self, *screens, title=None, db_name=None,
                 color="#6750A4", dynamic_color=False, locale=None, theme="auto", modules=None,
                 sync=None, python_packages=None, logic=None):
        from .ui.screen import Screen

        #: Loaded modules, when the app was assembled from a module directory.
        self.modules = list(modules or [])

        #: Логика, объявленная **самим приложением**, а не модулем. Нужна
        #: однофайловым приложениям: у них нет папки модулей, а объявить
        #: действие они вправе -- иначе «одно приложение = один файл»
        #: перестаёт быть правдой, как только появляется первая кнопка.
        self.logic = list(logic or [])

        #: Питоновские пакеты, которым место **на устройстве**: то, что в SQL
        #: не переводится -- словарная морфология, разбор чужого формата.
        #: Объявлены -- сборка везёт с собой настоящий CPython и эти колёса
        #: (около 13 МБ), не объявлены -- не везёт ничего. Ставятся из своих
        #: файлов, а не с PyPI: webview бывает без сети.
        self.python_packages = list(python_packages or [])

        #: Top-level destinations. A bare View is shorthand for one screen.
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
        #: Database file name. Defaults to one per app, because apps served
        #: from the same origin share a persistent filesystem -- a fixed name
        #: would silently merge two different applications into one database.
        #: Pass an explicit name to share one deliberately.
        self.db_name = db_name or f"{_slug(self.title)}.db"
        #: Material 3 seed colour -- the renderer derives the whole tonal
        #: palette (light and dark) from it. Defaults to the MD3 baseline.
        self.color = color
        #: UI-chrome language; ``None`` means follow the device.
        self.locale = locale
        #: Брать ли цвет у системы вместо объявленного.
        #:
        #: Из веба его не достать -- замерено и записано в
        #: `docs/probe-system-color.md`: живой Safari при красном акценте
        #: отдаёт постоянное синее, Chrome не знает ключа `AccentColor` вовсе.
        #: Material You выставлен только родному коду, палитрой ресурсов
        #: `system_accent1_*` с Android 12. Поэтому это согласие, а не замена:
        #: объявленный цвет остаётся лицом приложения и работает везде, а
        #: системный перебивает его там, где платформа его правда даёт.
        self.dynamic_color = bool(dynamic_color)

        #: Framework7 theme: "auto" (Material 3 everywhere, the iOS look on
        #: Apple devices), or pin one with "md" / "ios".
        self.theme = theme
        #: Куда ходить за обменом. Три состояния, и у каждого свой смысл:
        #: ``None`` -- «туда же, откуда приехала страница», то есть веб-клиент,
        #: отданный самим сервером обмена, работает без единой настройки;
        #: строка -- явный адрес, и он нужен там, где страницы неоткуда взять
        #: (APK живёт на своём origin внутри вебвью); ``False`` -- обмена нет.
        #: Сборка может задать то же самое переменной ``PYAPP_SYNC_URL``, не
        #: трогая ``app.py`` -- одно приложение, два стенда.
        self.sync = sync

        # What this app is made of. A `ui` method builds its tree from live
        # data, so there is no tree to walk before the schema exists -- and the
        # question was never really "which models does the UI reach" but "which
        # models does this app consist of". That is the code it is written in:
        # the modules it installs, or the file its views live in.
        packages = _source_packages(self.modules, self.screens)
        self.models = _models_in(packages)
        #: Every View the app declares -- what `oneframework check` walks. Not used to
        #: render: a screen finds its children by drawing them.
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

    #: ``start()`` жил здесь до 21.08.2026: он выкладывал приложение и тут же
    #: поднимал питоновский рантайм. Рантайма больше нет -- он на устройстве, --
    #: и осталась одна выкладка. Кому нужен исполненный кадр, тот спрашивает
    #: устройство: `libs/js/src/inspect-host.mjs` или `tests/parity/rt_host.mjs`.

    # -- бизнес-логика в WASM ---------------------------------------------
    def logic_modules(self):
        """Вся логика приложения. Пусто -- значит логики нет.

        Прежде всего -- та, что объявлена **на моделях**: там ей и место, это
        поведение записи. Спрашивать её у приложения не приходится, приложение
        само обходит свои модели.

        Остаются два прежних источника: логика, объявленную модулем, и логика,
        названная в самом ``App(logic=...)``. Второе нужно компилируемым
        языкам -- их тело живёт своим файлом, -- и приложениям, где действие
        не принадлежит ни одной модели.
        """
        out = []
        for model in self.models:
            actions = [a.declaration() for a in getattr(model, "_actions", ())]
            if actions:
                out.append({"actions": actions})
        out += list(self.logic)
        for module in self.modules:
            out.extend(module.logic)
        return out


    #: ``attach_logic()`` жил здесь: он поднимал питоновский хост логики
    #: (``wasm.Api``) и ставил базе проверку при сохранении. Звал его только
    #: ``start()``. Оба удалены 21.08.2026 -- логику на устройстве подключает
    #: `web/src/runtime/worker.js::attachLogic` тем же ходом и из той же базы.
    #: Выкладка модулей (``publish_logic`` выше) осталась: она -- работа сборки.

    def _seeded_before(self, db, name):
        """Was this seed already run under an earlier marker scheme?

        Markers used to be app-wide, then per-app. An installed app must not
        re-seed just because the framework changed how it names them.
        """
        if name != "app":
            return False
        return bool(db.get_meta(f"seeded:{_slug(self.title)}") or db.get_meta("seeded"))

    def _seeds(self, explicit=None):
        """``(name, fn)`` for every seed to consider, modules first.

        Each is marked independently, so adding a module to an existing
        installation seeds only the new one.
        """
        out = [(m.name, m.seed) for m in self.modules if m.seed]
        if explicit is not None:
            out.append(("app", explicit))
        return out

    def static_files(self, suffix=".js"):
        """Extra assets contributed by modules (custom widgets, styles)."""
        files = []
        for module in self.modules:
            files.extend(module.static_files(suffix))
        return files

    def __repr__(self):
        modules = f" modules={[m.name for m in self.modules]}" if self.modules else ""
        return f"<App {self.title!r} root={self.root_view.__name__}{modules}>"


def _source_packages(modules, screens):
    """The top-level Python packages this app is written in."""
    if modules:
        return {m.name for m in modules}
    # A single-file app: `app.py` holds the models and the views alike.
    return {(s.view.__module__ or "").split(".")[0] for s in screens}


def _defined_in(packages, meta):
    """Every class of *meta* defined in those packages, in a stable order.

    Read off the module namespaces rather than a global registry: a registry is
    keyed by class name, so two apps in one process (a test suite, say) with a
    ``Task`` each would shadow one another in it.
    """
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
    """Every model of the app, plus whatever its relations point at."""
    seen, order = set(), []

    def add(model):
        if model is None or model in seen:
            return
        seen.add(model)
        order.append(model)
        # A relation may cross into a package this app did not name -- a shared
        # library of lookup tables. Its table has to exist all the same.
        for rel in model.relations():
            add(rel.resolve_comodel())

    for model in _defined_in(packages, ModelMeta):
        add(model)
    return order


def _screens_from_modules(modules):
    """Destinations contributed by modules.

    A module adds a section to the app by declaring ``SCREEN``; installing the
    module is what puts it in the navigation. ``ROOT = <View>`` is still
    honoured as the single-screen shorthand.
    """
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


#: ``publish`` и ``publish_logic`` жили здесь: они раскладывали приложение по
#: базе -- схема, определения, посев, логика. Всё это делает теперь сборщик на
#: JS по плану от `oneframework/cli/plan.py`: питон говорит, что класть, кладёт
#: тот же код, каким база живёт на устройстве.
