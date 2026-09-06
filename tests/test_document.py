"""Соответствие: документ вида как формат.

Провод закреплён ``protocol/wire.json`` и ``tests/js/wire.test.mjs``; документ --
второй формат, который уезжает по сети, и сторожится он здесь.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import нужно_ядро

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "protocol" / "document.json").read_text(encoding="utf-8"))
ACTION_TYPES = frozenset(SCHEMA["actions"])
NODE_TYPES = frozenset(SCHEMA["nodes"])

ОБРАЗЦЫ = ("parity_app", "document_app")

_COLLECT = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from oneframework.ui.view import document
app = __import__(sys.argv[3]).app
# Без try: молча пропущенный вид -- ровно та ошибка, которую этот файл ловит.
# publish_views глотает TypeError, и один неверный ir() однажды уже увёл три
# вида из выкладки, ничего не сказав.
print(json.dumps([[v.__name__, document(v)] for v in app.views], ensure_ascii=False))
"""

def _documents():
    """``(пример, имя вида, документ)`` для каждого вида каждого примера."""
    out = []
    for example in ОБРАЗЦЫ:
        proc = subprocess.run(
            [sys.executable, "-c", _COLLECT, str(ROOT),
             str(ROOT / "tests" / "fixtures"), example],
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

# --- схема -------------------------------------------------------------------
def test_examples_produce_documents():
    """Каждый вид образца -- документ. Ни одного молчаливого пропуска."""
    assert DOCUMENTS, "образцы не дали ни одного документа -- сбор сломан"
    # Каждый образец обязан вложиться: молча выпавший унёс бы с собой то
    # единственное свойство, ради которого заведён.
    assert {и for и, _, _ in DOCUMENTS} == set(ОБРАЗЦЫ)
    for _example, name, doc in DOCUMENTS:
        assert doc["type"] == "view", name
        assert doc["name"] == name

    # Широта -- родами узлов, а не числом документов.
    роды = set()
    def обойти(узел):
        if isinstance(узел, dict):
            if "type" in узел: роды.add(узел["type"])
            for з in узел.values(): обойти(з)
        elif isinstance(узел, list):
            for э in узел: обойти(э)
    обойти([d for _e, _n, d in DOCUMENTS])
    assert len(роды) >= 12, f"образцы задевают только {sorted(роды)}"

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
# показывает всё, и это законный ответ.

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
    for _example, name, doc in DOCUMENTS:
        assert doc["dismiss"] in ("auto", "back", "close"), name
        assert isinstance(doc["state"], list), name
        assert doc["title"] is None or isinstance(doc["title"], str), name
        assert isinstance(doc["title_is_code"], bool), name
        if doc["title_is_code"]:
            assert doc["title"] is None, name

def test_views_still_holding_code_are_counted_not_hidden():
    """Вид с заголовком-функцией -- ещё программа, и документ говорит об этом."""
    holding = [n for _e, n, d in DOCUMENTS if d["title_is_code"]]
    # Ровно один, и он заведён ради этой проверки: `Карточка` в
    # `tests/fixtures/document_app.py`, у неё `_title` -- функция от записи
    # («Новая заметка» / «Правка заметки»).
    assert holding == ["Карточка"], holding

@нужно_ядро
def test_nothing_is_skipped_silently():
    """У примеров все виды обязаны публиковаться."""
    script = r"""
import json, sys, tempfile
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
import os; sys.path.insert(0, os.path.join(os.getcwd(), 'tests'))
from conftest import план
from oneframework.declaration import Bundle, declare
from oneframework.model.skipped import SKIPPED

# Что поедет в базу -- это **план**: пропуск вида решается при сборке
# документов, а не при записи, и спрашивать надо там же.
app = __import__(sys.argv[3]).app
план = план(Bundle(declare(app)))
print(json.dumps({"skipped": SKIPPED,
                  "published": [и for в, и, _ in план["defs"] if в == "view"],
                  "declared": [v.__name__ for v in app.views]}, ensure_ascii=False))
"""
    for example in ОБРАЗЦЫ:
        proc = subprocess.run(
            [sys.executable, "-c", script, str(ROOT),
             str(ROOT / "tests" / "fixtures"), example],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        assert proc.returncode == 0, f"{example}: {proc.stderr}"
        report = json.loads(proc.stdout)
        assert report["skipped"] == {}, f"{example}: пропущены {report['skipped']}"
        assert sorted(report["published"]) == sorted(report["declared"]), example

def test_state_fields_carry_their_type():
    drafts = [d for _e, n, d in DOCUMENTS if n == "Черновик"]
    assert drafts, "образец с состоянием вида не собрался"
    state = {f["name"]: f["ftype"] for f in drafts[0]["state"]}
    assert state == {"body_shown": "boolean", "done_shown": "boolean"}

#: Рубеж на форме документа уехал в ядро: он один на все три языка и стоит
#: на дороге сборки -- `libs/js/src/build/docschema.mjs`, сторож при нём
#: `tests/js/docschema.test.mjs`. Здесь он стоял на дороге, которой продукт
#: не ездит: его звал `view_defs`, второй писатель определений, -- и форма
#: документа не сверялась нигде на дороге, которая вправду ездит.
