"""Пакет объявления -- шов между языком и сборкой.

До сих пор приложение было питоновским объектом: сборщик получал ``App`` и
спрашивал у него ``.models``, ``.views``, ``.meta()``. Значит написать
приложение можно было только на питоне, и обещание «библиотека на каждом языке»
упиралось не в язык, а в этот вызов.

Шов проходит здесь. Сборка больше не спрашивает у объекта -- она читает
**пакет объявления**: обычный JSON, в котором лежит всё, из чего состоит
приложение::

    {"oneframework": 1,
     "app":    {"title": ..., "root": ..., "screens": [...], ...},
     "types":  {...},                    # свойства типов полей
     "models": [{...}, ...],             # документы моделей
     "views":  [{...}, ...],             # документы видов
     "logic":  [{"actions": [...]}]}     # логика на устройстве

Выше -- набросок; полная форма пакета записана договором,
``protocol/declaration.json``, и приложена к живым пакетам всех трёх языков в
``tests/test_declaration.py``.

Питон умеет пакет **порождать** (:func:`declare` -- из ``App``) и
**принимать** (:class:`Bundle` -- собрать из него приложение). Второе и есть
то, ради чего всё: пакет, порождённый библиотекой на Kotlin или на JavaScript,
собирается тем же сборщиком и даёт тот же результат.

Что здесь намеренно **не** делается: пакет не превращается обратно в
питоновские классы моделей и видов. Соблазн был -- тогда заработал бы весь
существующий сборщик даром. Но восстановленный класс молча дотянул бы
умолчания из питона, и дыра в объявлении -- поле, чьё свойство не доехало --
осталась бы невидимой ровно до тех пор, пока приложение собирает питон. Здесь
из пакета читается только то, что в пакете есть.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import OneFrameworkError
from .model.ids import new_id, seeded_ids

__all__ = ["VERSION", "declare", "Bundle", "load", "DeclarationError"]

#: Версия договора пакета. Меняется, когда меняется его форма, --
#: одновременно с ``version`` в ``protocol/declaration.json``: равенства
#: требует тест, чтобы номер в договоре не остался вчерашним.
VERSION = 1


class DeclarationError(OneFrameworkError):
    """Пакет объявления неполон или собран не по договору."""


# --------------------------------------------------------------------------
# питон -> пакет
# --------------------------------------------------------------------------
def declare(app, seed=None) -> dict:
    """``App`` -> пакет объявления.

    Ровно то же знание, что сборщик раньше добывал вызовами: те же документы
    моделей, те же документы видов, та же логика. Разница в том, что теперь оно
    записано, а не получено вопросами, -- а записанное умеет порождать и
    Kotlin.

    ``seed`` -- функция демо-данных (``seed.py`` рядом с приложением). Она
    **прогоняется здесь**, и в пакет едут уже строки. Раньше её прогоняла
    сборка, и из-за этого пакет был беднее приложения: сборка из ``.json``
    отказывалась вслух, а собрать то же самое без питона было нельзя. Посев --
    единственное, чем дороги расходились; теперь не расходятся.
    """
    from .model.defs import SKIPPED
    from .model.schema import model_schema, type_schema
    from .ui.view import document

    views = []
    SKIPPED.clear()
    for view in app.views:
        try:
            views.append(document(view))
        except Exception as exc:                      # noqa: BLE001
            # Тем же правилом, что и `publish_views`: вид, который ещё
            # программа, документа не даёт -- но пропуск записывается.
            SKIPPED[view.__name__] = f"{type(exc).__name__}: {exc}"

    return {
        "oneframework": VERSION,
        "app": {
            "title": app.title,
            "db_name": app.db_name,
            "root": app.root_view.__name__,
            "screens": [s.ir() for s in app.screens],
            "color": app.color,
            "dynamic_color": getattr(app, "dynamic_color", False),
            "locale": app.locale,
            "theme": app.theme,
            "sync": app.sync,
            "python_packages": list(app.python_packages),
            "maven": list(getattr(app, "maven", ())),
        },
        "types": type_schema(app.models),
        "models": [model_schema(m) for m in app.models],
        "views": views,
        "logic": app.logic_modules(),
        # Ключом, а не по наличию -- тем же правилом, что «logic»: пустой
        # список значит «демо-данных нет», отсутствие ключа значит потерянный
        # раздел, и по пакету их не различить.
        "seeds": record_seeds(app, seed),
    }


class Посев:
    """База для посева: принимает строки и раздаёт ключи, ничего не храня.

    Посевы зовут ровно два метода -- ``create`` и ``all`` (замерено по всем
    примерам). Всё остальное, что было у настоящей базы, здесь и не нужно:
    пакет несёт список намерений, а не состояние.
    """

    def __init__(self):
        self.строки: dict[str, list[dict]] = {}
        self.связи: list[dict] = []

    def create(self, model, values=None):
        значения = dict(values or {})
        ключ = значения.get("id") or new_id()
        значения["id"] = ключ
        self.строки.setdefault(model.__name__, []).append(значения)
        return ключ

    def all(self, model, **_):
        return [dict(r) for r in self.строки.get(model.__name__, ())]

    def set_many2many(self, field, owner_id, ids):
        """Связь многие-ко-многим -- тоже намерение, а не запись.

        Поле за провод не проходит, поэтому едет его адрес: модель-владелец и
        имя поля. Кто такое поле, на той стороне знает `makeModels`.
        """
        self.связи.append({"model": field.owner.__name__, "field": field.name,
                           "owner": owner_id, "ids": list(ids or [])})

    # Посевам этого не нужно, но `App.publish` звал -- пусть отказывает громко,
    # а не делает вид, что записал.
    def __getattr__(self, имя):
        raise AttributeError(
            f"Пакет объявления не умеет {имя!r}: он несёт список намерений, а не "
            "пишет базу. Пишет её `libs/js/src/build-db.mjs`.",
        )


def record_seeds(app, seed=None):
    """Прогнать посевы приложения и вернуть их строками.

    Каждый посев со своей отметкой: отметка и решает, сеять ли. База может быть
    непустой (``inspect --db`` открывает ту, что уже есть у пользователя), и
    второй посев положил бы те же записи ещё раз.
    """
    записанное = []
    for имя, fn in app._seeds(seed):
        строки = Посев()
        # Тот же поток ключей, что у настоящей выкладки: посев обязан давать
        # одни и те же ключи на всех клиентах.
        with seeded_ids(f"{_slug(app.title)}:{имя}"):
            fn(строки)
        # Отметки прежних схем имени -- тоже. Приложение, посеянное старой
        # версией каркаса, не должно сеять заново только потому, что каркас
        # переименовал отметку: демо-данные удвоились бы молча.
        прежние = ([f"seeded:{_slug(app.title)}", "seeded"] if имя == "app" else [])
        записанное.append({"mark": f"seeded:{_slug(app.title)}:{имя}",
                           "also": прежние,
                           "rows": строки.строки, "links": строки.связи})
    return записанное


# --------------------------------------------------------------------------
# пакет -> приложение
# --------------------------------------------------------------------------
class Bundle:
    """Приложение, собранное из пакета объявления.

    Отвечает на те же вопросы, что ``App``, и умеет то же, что нужно сборке:
    завести схему, выложить определения, положить логику. Чем написано
    приложение -- питоном, Kotlin или JavaScript -- отсюда уже не видно, и в
    этом весь смысл.
    """

    def __init__(self, doc, *, source=None):
        version = doc.get("oneframework")
        if version != VERSION:
            raise DeclarationError(
                f"Пакет объявления версии {version!r}, а эта сборка понимает "
                f"{VERSION}. Обновите библиотеку своего языка."
            )
        # Перечень -- из договора, а не свой: разойдись они, `protocol/`
        # обещал бы одно, а сборка требовала другое. `logic` здесь не значился
        # до 21.08.2026 -- договор его обязательность объявлял, проверка не
        # спрашивала, и пакет без логики проезжал молча.
        for key in ("app", "types", "models", "views", "logic", "seeds"):
            if key not in doc:
                raise DeclarationError(f"В пакете объявления нет раздела «{key}».")

        self.doc = doc
        #: Откуда пакет приехал -- показывается в сообщениях об отказе.
        self.source = source
        сведения = doc["app"]
        self.title = сведения["title"]
        self.color = сведения.get("color", "#6750A4")
        self.dynamic_color = сведения.get("dynamic_color", False)
        self.locale = сведения.get("locale")
        self.theme = сведения.get("theme", "auto")
        self.sync = сведения.get("sync")
        self.root_view = сведения["root"]
        self.screens = сведения.get("screens") or []
        self.python_packages = list(сведения.get("python_packages") or [])
        #: Зависимости с Maven Central: «группа:артефакт:версия». Нужны сборке
        #: модуля, на устройство сами по себе не едут -- туда попадает только
        #: то, до чего дотянулась логика.
        self.maven = list(сведения.get("maven") or [])
        self.db_name = сведения.get("db_name") or f"{_slug(self.title)}.db"
        self.types = doc["types"]
        self.model_docs = doc["models"]
        self.view_docs = doc["views"]
        self.logic = doc["logic"] or []
        #: Демо-данные строками. Пустой список -- законный ответ «их нет».
        self.seeds = doc.get("seeds") or []
        self._check()

    # -- проверка ---------------------------------------------------------
    def _check(self):
        """Поймать неполный пакет здесь, а не в пустом экране на устройстве.

        Проверяется то, чего сборка не переживёт: неизвестный тип поля, вид,
        привязанный к несуществующей модели, корневой вид, которого нет.
        Остальное -- дело того языка, что пакет породил.
        """
        имена_моделей = {m["name"] for m in self.model_docs}
        for модель in self.model_docs:
            for поле in модель["fields"]:
                if поле["ftype"] not in self.types:
                    raise DeclarationError(
                        f"{модель['name']}.{поле['name']}: тип «{поле['ftype']}» "
                        f"не описан в разделе «types» пакета. Известны: "
                        f"{', '.join(sorted(self.types))}."
                    )
        имена_видов = {v["name"] for v in self.view_docs}
        for вид in self.view_docs:
            модель = вид.get("model")
            if модель is not None and модель not in имена_моделей:
                raise DeclarationError(
                    f"Вид «{вид['name']}» привязан к модели «{модель}», "
                    f"которой в пакете нет."
                )
        if self.root_view not in имена_видов:
            raise DeclarationError(
                f"Корневой вид «{self.root_view}» не объявлен. Есть: "
                f"{', '.join(sorted(имена_видов)) or 'ни одного'}."
            )

    # -- то, что спрашивает сборка ----------------------------------------
    def meta(self):
        """Сведения, которые рантайм читает **до** первого запроса к базе.

        Собираются здесь, а не в каждой библиотеке: это производная от типов и
        моделей, и требовать её от Kotlin значило бы просить его повторить
        вывод, который и так однозначен.
        """
        return {
            "title": self.title,
            "root": self.root_view,
            "screens": self.screens,
            "color": self.color,
            "locale": self.locale,
            "theme": self.theme,
            "sync": self.sync,
            "models": {
                м["name"]: {
                    "label": м.get("label", м["name"]),
                    "table": м["table"],
                    "display_field": _display_field(м),
                    "fields": {
                        поле["name"]: {
                            "type": поле["ftype"],
                            "label": _display_label(поле),
                            "required": bool(поле.get("required", False)),
                            "widgets": list(self.types[поле["ftype"]]["widgets"]),
                            "default_widget": (
                                поле.get("widget") or self.types[поле["ftype"]]["widget"]
                            ),
                            # Только у ссылки на одну запись: рантайм спрашивает
                            # comodel, чтобы нарисовать выбор. У набора записей
                            # выбирать нечего, и питон здесь тоже молчит.
                            "comodel": (поле.get("comodel")
                                        if поле["ftype"] in ("many2one", "one2one")
                                        else None),
                        }
                        for поле in _fields_in_model_order(м)
                    },
                }
                for м in self.model_docs
            },
        }

    def logic_modules(self):
        return list(self.logic)

    def static_files(self, suffix=".js"):
        return []

    # -- сборка -----------------------------------------------------------
    #: ``start`` жил здесь и выкладывал пакет в базу сам. Выкладывает теперь
    #: сборщик (`libs/js/src/build-db.mjs`) по плану от `cli/plan.py` -- тот же,
    #: что и у приложения на питоне: две дороги, один писатель.

    #: ``ensure_schema`` строил DDL прямо из документов -- третья запись
    #: правила создания таблиц, названная в своей же шапке осознанным долгом.
    #: Долг закрыт 21.08.2026: таблицы заводит одна реализация,
    #: `db.ensureSchema` на устройстве, а пакет отдаёт ей то же описание, что и
    #: приложение (`cli/plan.py`). Совпадение описаний сторожит
    #: ``tests/test_protocol.py``.


    def __repr__(self):
        откуда = f" из {self.source}" if self.source else ""
        return (f"<Bundle {self.title!r} моделей={len(self.model_docs)} "
                f"видов={len(self.view_docs)}{откуда}>")


# --------------------------------------------------------------------------
# вспомогательное
# --------------------------------------------------------------------------
def load(path) -> Bundle:
    """Прочитать пакет из файла."""
    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as отказ:
        raise DeclarationError(f"{path}: это не JSON -- {отказ}") from None
    return Bundle(doc, source=str(path))


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return slug or "app"






def _fields_in_model_order(модель):
    """Порядок, в котором поля лежат у модели: сперва ``id``, потом объявленные.

    Документ печатает поля в порядке объявления, а ``meta`` -- в порядке
    словаря ``_fields``, и это разные порядки. Разница видна на устройстве:
    первым в карточке рисуется первое поле, и перепутать их значит переставить
    экран.
    """
    from .protocol import SYSTEM_FIELD_ORDER

    по_имени = {f["name"]: f for f in модель["fields"]}
    порядок = [по_имени["id"]] if "id" in по_имени else []
    порядок += [f for f in модель["fields"] if f["name"] not in SYSTEM_FIELD_ORDER]
    порядок += [по_имени[n] for n in SYSTEM_FIELD_ORDER[1:] if n in по_имени]
    return порядок


def _display_label(поле):
    """Подпись поля на экране: объявленная, иначе выведенная из имени.

    Правило то же, что у :meth:`Field.display_label`. В документе подпись
    лежит, только если её объявили, -- поэтому вывести её обязан тот, кто
    документ читает, и обязан ровно так же, иначе у Kotlin-приложения поле
    подпишется иначе, чем у питоновского.
    """
    return поле.get("label") or поле["name"].replace("_", " ").capitalize()


def _display_field(модель):
    """Чем запись называется: ``name``, иначе первая строка, иначе ничего.

    Правило то же, что у :meth:`Model.display_field`, и записано вторым разом
    по той же причине, что DDL: пакет читается без питоновских классов.
    """
    поля = [f for f in модель["fields"] if not f.get("system")]
    for f in поля:
        if f["name"] == "name":
            return "name"
    for f in поля:
        if f["ftype"] == "string":
            return f["name"]
    return None


#: ``publish_logic`` жил здесь -- питоновская выкладка модулей пакета. Кладёт
#: их теперь сборщик по общему плану: у пакета и у приложения на питоне дорога
#: одна.


#: ``_stored_fields`` и ``_column`` жили здесь -- помощники `Bundle.ensure_schema`,
#: удалённой вместе с третьей записью правила создания таблиц.
