"""Пакет объявления -- шов между языком и сборкой."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import OneFrameworkError
from .model.ids import new_id, seeded_ids

__all__ = ["VERSION", "declare", "Bundle", "load", "DeclarationError"]

VERSION = 1

class DeclarationError(OneFrameworkError):
    """Пакет объявления неполон или собран не по договору."""
# --- питон -> пакет ----------------------------------------------------------
def declare(app, seed=None) -> dict:
    """``App`` -> пакет объявления."""
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
        """Связь многие-ко-многим -- тоже намерение, а не запись."""
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
    записанное = []
    for имя, fn in app._seeds(seed):
        строки = Посев()
        # Тот же поток ключей, что у настоящей выкладки: посев обязан давать
        # одни и те же ключи на всех клиентах.
        with seeded_ids(f"{_slug(app.title)}:{имя}"):
            fn(строки)
        прежние = ([f"seeded:{_slug(app.title)}", "seeded"] if имя == "app" else [])
        записанное.append({"mark": f"seeded:{_slug(app.title)}:{имя}",
                           "also": прежние,
                           "rows": строки.строки, "links": строки.связи})
    return записанное

# --- пакет -> приложение -----------------------------------------------------
class Bundle:
    def __init__(self, doc, *, source=None):
        version = doc.get("oneframework")
        if version != VERSION:
            raise DeclarationError(
                f"Пакет объявления версии {version!r}, а эта сборка понимает "
                f"{VERSION}. Обновите библиотеку своего языка."
            )
        # Перечень -- из договора, а не свой: разойдись они, `protocol/` обещал
        # бы одно, а сборка требовала другое, и пакет без раздела проезжал бы
        # молча.
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
        self.maven = list(сведения.get("maven") or [])
        self.db_name = сведения.get("db_name") or f"{_slug(self.title)}.db"
        self.types = doc["types"]
        self.model_docs = doc["models"]
        self.view_docs = doc["views"]
        self.logic = doc["logic"] or []
        self.seeds = doc.get("seeds") or []
        self._check()

    # -- проверка ---------------------------------------------------------
    def _check(self):
        """Поймать неполный пакет здесь, а не в пустом экране на устройстве."""
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
                            # Только у ссылки на одну запись: рантайм
                            # спрашивает comodel, чтобы нарисовать выбор.
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
    # Пакет в базу выкладывает сборщик (`libs/js/src/build-db.mjs`) по плану от
    # `cli/plan.py`: у пакета и у приложения на питоне дорога одна.

    #: Таблицы заводит одна реализация -- `db.ensureSchema` на устройстве, а
    #: пакет отдаёт ей то же описание, что и приложение (`cli/plan.py`).

    def __repr__(self):
        откуда = f" из {self.source}" if self.source else ""
        return (f"<Bundle {self.title!r} моделей={len(self.model_docs)} "
                f"видов={len(self.view_docs)}{откуда}>")

# --- вспомогательное ---------------------------------------------------------
def load(path) -> Bundle:
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
    """Порядок, в котором поля лежат у модели: сперва ``id``, потом объявленные."""
    from .protocol import SYSTEM_FIELD_ORDER

    по_имени = {f["name"]: f for f in модель["fields"]}
    порядок = [по_имени["id"]] if "id" in по_имени else []
    порядок += [f for f in модель["fields"] if f["name"] not in SYSTEM_FIELD_ORDER]
    порядок += [по_имени[n] for n in SYSTEM_FIELD_ORDER[1:] if n in по_имени]
    return порядок

def _display_label(поле):
    """Подпись поля на экране: объявленная, иначе выведенная из имени."""
    return поле.get("label") or поле["name"].replace("_", " ").capitalize()

def _display_field(модель):
    """Чем запись называется: ``name``, иначе первая строка, иначе ничего."""
    поля = [f for f in модель["fields"] if not f.get("system")]
    for f in поля:
        if f["name"] == "name":
            return "name"
    for f in поля:
        if f["ftype"] == "string":
            return f["name"]
    return None
