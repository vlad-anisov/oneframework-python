"""Соответствие: документ вида как формат.

Провод закреплён ``protocol/wire.json`` и ``tests/js/wire.test.mjs``. Документ --
второй формат, который уезжает по сети, и до сих пор он не был описан нигде.
Разница между ними существенная, а не версионная:

* **снимок** несёт разрешённые значения -- «вот эти строки, вот это число»;
* **документ** несёт объявления -- «вот по какому домену строки брать».

Поэтому у документа своя схема и свой тест, а не флаг в чужом.

Два правила держат весь файл:

* каждый узел и каждое действие документа перечислены в схеме -- с ключами,
  которые они обязаны нести;
* объявление обязано быть на месте: у списка -- домен, у фильтра -- домен, у
  сортировки -- порядок, у действия -- то, над чем оно совершается.

Второе правило проверяется обходом **всего** документа, а не тех узлов, что
вспомнились. Дыра, которую этот файл заводился ловить, выглядела именно так:
документ описывал форму экрана и молчал о поведении, и никто этого не замечал,
потому что по документу ещё ни разу не рисовали.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "protocol" / "document.json").read_text(encoding="utf-8"))
ACTION_TYPES = frozenset(SCHEMA["actions"])
NODE_TYPES = frozenset(SCHEMA["nodes"])

EXAMPLES = ("gtasks", "kitchen", "modular")


#: Сбор документов идёт отдельным процессом на каждый пример.
#:
#: Не из осторожности: реестр моделей глобален и ключуется именем класса, а
#: ``Task`` есть в трёх примерах из четырёх. Загрузи их в один процесс -- и
#: связи начнут разрешаться в чужой класс, причём молча. Тот же самый довод
#: записан в ``App._defined_in``, и здесь он ровно про то же.
_COLLECT = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from oneframework.ui.view import document
app = __import__("app").app
# Без try: молча пропущенный вид -- ровно та ошибка, которую этот файл ловит.
# publish_views глотает TypeError, и один неверный ir() однажды уже увёл три
# вида из выкладки, ничего не сказав.
print(json.dumps([[v.__name__, document(v)] for v in app.views], ensure_ascii=False))
"""


def _documents():
    """``(пример, имя вида, документ)`` для каждого вида каждого примера."""
    out = []
    for example in EXAMPLES:
        proc = subprocess.run(
            [sys.executable, "-c", _COLLECT, str(ROOT), str(ROOT / "examples" / example)],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        assert proc.returncode == 0, f"{example}: {proc.stderr}"
        for name, doc in json.loads(proc.stdout):
            out.append((example, name, doc))
    return out


DOCUMENTS = _documents()


def walk(node):
    """Каждый словарь документа, у которого есть ``type``."""
    if isinstance(node, dict):
        if isinstance(node.get("type"), str):
            yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def typed(kind):
    for _example, _view, doc in DOCUMENTS:
        for node in walk(doc):
            if node.get("type") == kind:
                yield node


# --------------------------------------------------------------------------
# схема
# --------------------------------------------------------------------------
def test_examples_produce_documents():
    """Каждый вид примеров -- документ. Ни одного молчаливого пропуска."""
    assert len(DOCUMENTS) >= 29
    for _example, name, doc in DOCUMENTS:
        assert doc["type"] == "view", name
        assert doc["name"] == name


def test_every_node_type_is_described():
    """Новый тип узла без правки схемы роняет тест -- в этом и смысл."""
    seen = {
        node["type"]
        for _e, _v, doc in DOCUMENTS
        for node in walk(doc)
        if node["type"] not in ACTION_TYPES
    }
    assert seen <= NODE_TYPES, f"нет в схеме: {sorted(seen - NODE_TYPES)}"


def test_every_action_type_is_described():
    seen = {n["type"] for _e, _v, doc in DOCUMENTS for n in walk(doc)} & ACTION_TYPES
    unknown = {
        n["type"]
        for _e, _v, doc in DOCUMENTS
        for n in walk(doc)
        if "action" in str(n.get("type")) and n["type"] not in ACTION_TYPES
    }
    assert not unknown
    assert seen  # действия в примерах есть, иначе тест ничего не проверяет


@pytest.mark.parametrize("kind", sorted(NODE_TYPES))
def test_node_carries_its_required_keys(kind):
    spec = SCHEMA["nodes"][kind]
    allowed = set(spec["required"]) | set(spec["optional"])
    for node in typed(kind):
        missing = set(spec["required"]) - set(node)
        assert not missing, f"{kind}: нет ключей {sorted(missing)}"
        extra = set(node) - allowed
        assert not extra, f"{kind}: ключи вне схемы {sorted(extra)}"


@pytest.mark.parametrize("kind", sorted(ACTION_TYPES))
def test_action_carries_its_required_keys(kind):
    spec = SCHEMA["actions"][kind]
    allowed = set(spec["required"]) | set(spec["optional"])
    for node in typed(kind):
        missing = set(spec["required"]) - set(node)
        assert not missing, f"{kind}: нет ключей {sorted(missing)}"
        assert not set(node) - allowed


# --------------------------------------------------------------------------
# полнота: объявление обязано быть на месте
# --------------------------------------------------------------------------
# Ключ обязан присутствовать, а значение может быть пустым: список без домена
# показывает всё, и это законный ответ. Проверяется именно наличие объявления --
# отсутствие ключа означает, что вопрос потерян, а не что ответ «всё».


def test_every_list_declares_its_query():
    lists = list(typed("list"))
    assert lists
    for node in lists:
        assert "domain" in node, f"список {node['id']} не говорит, что показывать"
        assert "order" in node, f"список {node['id']} не говорит, в каком порядке"


def test_every_filter_declares_its_domain():
    for node in typed("filter"):
        assert "domain" in node, f"фильтр {node['id']} ничего не отбирает"


def test_every_sort_declares_its_order():
    sorts = list(typed("sort"))
    assert sorts
    for node in sorts:
        assert node.get("orders"), f"сортировка {node['id']} ничем не сортирует"


def test_every_repeat_declares_its_model():
    for node in typed("repeat"):
        assert node.get("model"), "повторитель без модели -- пустое место"


def test_delete_declares_what_it_removes():
    """``Delete(Board, item.id)``, ``Task.search(...).delete()`` и голый
    ``Delete()`` обязаны различаться в документе: делают они разное."""
    for node in typed("delete"):
        assert "model" in node and "record_id" in node and "domain" in node


def test_open_and_create_declare_their_target():
    for node in typed("open"):
        assert node.get("view"), "Open без вида никуда не ведёт"
        assert "record_id" in node and "target" in node
    for node in typed("create"):
        assert node.get("model"), "Create без модели нечего создавать"
        assert "values" in node and "draft" in node and "target" in node


def test_set_declares_field_and_scope():
    for node in typed("set"):
        assert node.get("field") and node.get("scope") in ("record", "view")


def test_view_declares_its_own_metadata():
    """Заголовок, поведение кнопки «назад» и состояние экрана.

    Состояние особенно: `view.tag`, упомянутый только в домене, ни одним узлом
    в дереве не представлен, и без этого списка рантайм не узнал бы даже, что
    такое поле есть.
    """
    for _example, name, doc in DOCUMENTS:
        assert doc["dismiss"] in ("auto", "back", "close"), name
        assert isinstance(doc["state"], list), name
        assert doc["title"] is None or isinstance(doc["title"], str), name
        assert isinstance(doc["title_is_code"], bool), name
        if doc["title_is_code"]:
            assert doc["title"] is None, name


def test_views_still_holding_code_are_counted_not_hidden():
    """Вид с заголовком-функцией -- ещё программа, и документ говорит об этом.

    Молчаливая потеря заголовка была бы худшим из исходов: экран уехал бы без
    имени, и причина не нашлась бы нигде. Пока такие виды есть, они обязаны быть
    пересчитаны -- это и есть отчёт о том, где переезд.
    """
    holding = [n for _e, n, d in DOCUMENTS if d["title_is_code"]]
    # Ровно один на сегодня: BoardCard из gtasks, у него `_title` -- функция от
    # записи («Создать список» / «Переименовать список»).
    assert holding == ["BoardCard"], holding


def test_nothing_is_skipped_silently():
    """У примеров все виды обязаны публиковаться.

    ``publish_views`` ловит любое исключение -- иначе один непереехавший вид
    ронял бы чужое приложение на запуске. Цена этой терпимости -- что поломка
    фреймворка выглядит как «вид ещё программа»: опечатка в сигнатуре ``ir()``
    однажды увела три вида из выкладки, не сказав ни слова.

    Здесь эта цена и возвращается: пропуск записан с причиной, и у примеров
    список обязан быть пуст.
    """
    script = r"""
import json, sys, tempfile
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
from oneframework.cli.plan import build_plan
from oneframework.declaration import Bundle, declare
from oneframework.model.defs import SKIPPED

# Что поедет в базу -- это **план**: пропуск вида решается при сборке
# документов, а не при записи, и спрашивать надо там же.
app = __import__("app").app
план = build_plan(Bundle(declare(app)))
print(json.dumps({"skipped": SKIPPED,
                  "published": [и for в, и, _ in план["defs"] if в == "view"],
                  "declared": [v.__name__ for v in app.views]}, ensure_ascii=False))
"""
    for example in EXAMPLES:
        proc = subprocess.run(
            [sys.executable, "-c", script, str(ROOT), str(ROOT / "examples" / example)],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        assert proc.returncode == 0, f"{example}: {proc.stderr}"
        report = json.loads(proc.stdout)
        assert report["skipped"] == {}, f"{example}: пропущены {report['skipped']}"
        assert sorted(report["published"]) == sorted(report["declared"]), example


def test_state_fields_carry_their_type():
    drafts = [d for _e, n, d in DOCUMENTS if n == "TaskDraftCard"]
    assert drafts
    state = {f["name"]: f["ftype"] for f in drafts[0]["state"]}
    assert state == {"details_shown": "boolean", "date_shown": "boolean"}


# ==========================================================================
# рубеж: документ, не сходящийся с договором, до базы не доходит
# ==========================================================================
def test_a_document_that_breaks_the_contract_is_refused():
    """Определение -- исполняемая настройка, и форму её никто не проверял.

    ``put()`` принимала любой словарь: он ложился в ``_oneframework_def`` и
    уезжал обменом. Подпись издателя отвечает за то, *кто* прислал, а не за
    то, *что* прислано. Узел, которого отрисовка не знает, на устройстве
    выглядит пустым местом вместо части экрана -- и молчит.

    Нашёл разбор со стороны 20.08.2026.
    """
    from oneframework.model.defs import view_defs
    from oneframework.ui.nodes import Node
    from oneframework.ui.view import View

    #: Вид, чей документ несёт узел, которого договор не знает. Проверяется
    #: **выкладка**, а не запись: рубеж переехал туда 21.08.2026 вместе с ней.
    class Чужой(View):
        def ui(self, record):
            return ()

    целый = {"type": "view", "name": "X", "children": [], "crumbs": None,
             "dismiss": None, "model": None, "state": [], "title": "X",
             "title_is_code": False}
    from oneframework.model import docschema

    assert docschema.problems(целый) == [], "целый документ не прошёл"
    чужой = {**целый, "children": [{"type": "нетакого", "id": "n1"}]}
    беды = docschema.problems(чужой)
    assert беды and any("нетакого" in б for б in беды), беды

    #: И то же самое на настоящей выкладке: подменяем документ вида и смотрим,
    #: что она отказывает, а не кладёт молча.
    import oneframework.ui.view as вид_модуль

    настоящий = вид_модуль.document
    вид_модуль.document = lambda cls: чужой
    try:
        with pytest.raises(ValueError, match="нетакого"):
            view_defs([Чужой])
    finally:
        вид_модуль.document = настоящий


def test_the_gate_measures_actions_by_their_own_table():
    """Действия договор описывает порознь, и различает их место, а не тип.

    Первая редакция рубежа мерила действия формами узлов -- и объявила
    расхождением все 29 видов всех примеров. Проверка держит это различие.
    """
    from oneframework.model.docschema import problems

    целый = {"type": "view", "name": "X", "children": [], "crumbs": None,
             "dismiss": None, "model": None, "state": [], "title": "X",
             "title_is_code": False}
    сдействием = {**целый, "children": [
        {"type": "button", "id": "b1", "label": "Удалить", "icon": None,
         "place": None, "style": None, "visible": True, "enabled": True,
         "action": {"type": "delete", "model": "Task"}},
    ]}
    # Действие `delete` есть в `actions` и его нет в `nodes` -- значит рубеж,
    # меряющий его правильным словарём, к нему по типу не придерётся.
    беды = problems(сдействием)
    assert not [б for б in беды if "delete" in б and "неизвестен" in б]
