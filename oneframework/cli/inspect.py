"""``oneframework inspect`` -- приложение, разглядываемое без браузера.

Отладка здесь распадается надвое, и разделяет её документ вида. Документ --
чистая функция от объявлений: структура экрана, ссылки на поля, условия. Снимок
-- чистая функция от документа и данных. Значит вопрос «почему экран не такой»
всегда имеет ровно один первый шаг: **посмотреть на документ**. Неверный
документ -- это питон, и дальше смотреть здесь. Верный документ при неверном
экране -- это рантайм на JS, и дальше смотреть в DevTools. Без этого шага обе
половины отлаживаются одновременно и наугад.

Отсюда и состав команды: показать документ, показать снимок, послать событие и
показать **разницу** снимков. Разницу, а не два полотна: снимок экрана со
списком -- это десятки килобайт JSON, и «что изменилось от нажатия» в двух таких
полотнах человек не находит. Идея заимствована у Redux DevTools, где ценность не
в журнале действий, а в том, что рядом с каждым действием лежит diff состояния.

И одна вещь сверх этого -- ``--why``. Odoo в подсказке к полю показывает
объявленное ``Invisible: <выражение>`` и на этом останавливается; Airtable на
сломанной формуле пишет ``#ERROR!`` и не говорит, где. А спрашивают почти
всегда не «какое условие стоит», а «что оно дало **на этой записи**», и ответ
на это требует истолковать определение на данных -- то есть ровно того, чего
не сделает никакой сторонний просмотрщик базы.

Чего здесь намеренно нет: произвольных запросов, просмотра таблиц, фильтров по
данным. База -- обычный файл SQLite, и на нём уже бесплатно работают ``sqlite3``
и ``datasette``. Своё было бы хуже обоих. Проверка для всякой новой возможности
одна: ответит ли на это Datasette, читая один файл? Если да -- не писать.

Открывая настоящую базу (``--db``), команда работает на **копии**: смотреть
приходится в тот же файл, которым пользуется приложение, а событие, посланное
для проверки, -- это запись. Копия делает наблюдение безопасным по построению --
тот же приём, что ``rails console --sandbox``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple

from .. import core
from ..errors import OneFrameworkError
from ..model import defs
from ..ui.view import document

__all__ = [
    "Change", "diff", "format_diff", "keyed", "entries", "walk", "find_node",
    "comparable", "displayable", "resolve_id", "resolve_event", "render_tree",
    "render_screens", "explain_expr", "why", "refs", "where", "shell",
    "export_case", "open_app", "cmd_inspect", "add_parser",
]


# ---------------------------------------------------------------------------
# адресация внутри дерева
# ---------------------------------------------------------------------------
#: Ключ, по которому элементы списка называются и сопоставляются.
KEY = "id"


def keyed(items):
    """Список как ``{id: элемент}``, или ``None``, если так нельзя.

    Строки списка и кадры стека называются ключом, а не позицией. Иначе
    вставка одной задачи в начало объявляет изменившимися все строки до конца
    -- ровно то полотно, ради ухода от которого разница и делается, -- а путь,
    напечатанный вчера, назавтра указывает на другую запись.
    """
    if not items:
        return None
    keys = []
    for item in items:
        if not isinstance(item, dict) or KEY not in item:
            return None
        key = item[KEY]
        if not isinstance(key, (str, int)) or isinstance(key, bool):
            return None
        keys.append(key)
    if len(set(keys)) != len(keys):
        return None
    return dict(zip(keys, items))


def entries(items):
    """``(суффикс пути, элемент)`` для каждого элемента списка."""
    by_key = keyed(items)
    if by_key is None:
        return [(f"[{i}]", item) for i, item in enumerate(items)]
    return [(f"[{k}]", v) for k, v in by_key.items()]


def walk(node, path=""):
    """Каждый словарь дерева и путь до него -- в той же записи, что и разница."""
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from walk(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for suffix, item in entries(node):
            yield from walk(item, f"{path}{suffix}")


def row_label(entry):
    """Чем строка списка выглядит для человека -- первым же своим текстом.

    Строка на проводе -- вектор значений против общего описания, поэтому
    подпись ищется в ``v``, а не обходом узлов: узлов у строки больше нет.
    """
    for value in entry.get("v") or ():
        if isinstance(value, str) and value:
            return value
    # Случай, снятый до смены формы: выгруженные раньше эталоны и разница,
    # которую считают против них, должны остаться читаемыми.
    for _, node in walk(entry):
        value = node.get("value")
        if node.get("type") == "field" and isinstance(value, str) and value:
            return value
    return ""


def rows_of(snapshot, node_id):
    """Списки, в чьём описании строки стоит этот узел.

    Их бывает несколько: один вид строки рисует и «Помеченные», и список
    каждой доски, а номер узла у них общий.
    """
    out = []
    for _, node in walk(snapshot):
        if node.get("type") != "list":
            continue
        row = node.get("row") or {}
        if any(n.get(KEY) == node_id for _, n in walk(row)):
            out.append(node)
    return out


# ---------------------------------------------------------------------------
# разница двух снимков
# ---------------------------------------------------------------------------
class Change(NamedTuple):
    """Одно расхождение: ``op`` -- один из ``~ + - >``."""

    op: str
    path: str
    old: object
    new: object


def diff(old, new, path=""):
    """Все расхождения двух JSON-подобных значений, плоским списком."""
    if isinstance(old, dict) and isinstance(new, dict):
        return _diff_dict(old, new, path)
    if isinstance(old, list) and isinstance(new, list):
        return _diff_list(old, new, path)
    return [] if old == new and type(old) is type(new) else [Change("~", path, old, new)]


def _diff_dict(old, new, path):
    out = []
    keys = list(old) + [k for k in new if k not in old]
    for key in keys:
        where = f"{path}.{key}" if path else str(key)
        if key not in new:
            out.append(Change("-", where, old[key], None))
        elif key not in old:
            out.append(Change("+", where, None, new[key]))
        else:
            out.extend(diff(old[key], new[key], where))
    return out


def _diff_list(old, new, path):
    before, after = keyed(old), keyed(new)
    if before is None or after is None:
        out = []
        for i in range(min(len(old), len(new))):
            out.extend(diff(old[i], new[i], f"{path}[{i}]"))
        for i in range(len(new), len(old)):
            out.append(Change("-", f"{path}[{i}]", old[i], None))
        for i in range(len(old), len(new)):
            out.append(Change("+", f"{path}[{i}]", None, new[i]))
        return out

    out = []
    for key in before:
        if key not in after:
            out.append(Change("-", f"{path}[{key}]", before[key], None))
    for key, value in after.items():
        if key not in before:
            out.append(Change("+", f"{path}[{key}]", None, value))
        else:
            out.extend(diff(before[key], value, f"{path}[{key}]"))
    # Перестановка -- отдельное событие приложения, и списком расхождений по
    # содержимому она не видна вовсе: строки те же, порядок другой.
    kept_before = [k for k in before if k in after]
    kept_after = [k for k in after if k in before]
    if kept_before != kept_after:
        out.append(Change(">", path, kept_before, kept_after))
    return out


def comparable(snapshot):
    """Снимок без производных полей.

    ``stack`` -- это ``stacks[active]``, а ``depth`` -- его длина. Оставить их
    значило бы показывать каждое изменение активного раздела дважды.
    """
    return {k: v for k, v in snapshot.items() if k not in ("stack", "depth")}


def displayable(snapshot):
    """Снимок без удвоения: активный стек и так лежит в ``stacks``.

    Печатать оба значило бы отдать на глаз вдвое больше JSON, и путь, по
    которому узел найден, разошёлся бы с путём в разнице.
    """
    return {k: v for k, v in snapshot.items() if k != "stack"}


def brief(value, width=68):
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return text if len(text) <= width else text[: width - 1] + "…"


def summary(value):
    """Целый узел одной строкой.

    Появившаяся и исчезнувшая строка списка -- самое частое расхождение, и
    обрезанный JSON про неё не говорит ничего: у всех строк одинаковое начало.
    Название говорит всё.
    """
    if isinstance(value, dict):
        if "view" in value and "title" in value:
            return f"screen {value['view']} {value.get('title')!r}"
        label = row_label(value)
        if label:
            return f"{value.get('type') or 'row'} {label!r}"
    return brief(value)


def format_diff(changes, limit=60):
    """Расхождения как текст для терминала."""
    if not changes:
        return ["    (no change)"]
    lines = []
    for change in changes[:limit]:
        lines.append(f"    {change.op} {change.path}")
        if change.op in ("~", ">"):
            lines.append(f"        {summary(change.old)}  ->  {summary(change.new)}")
        else:
            lines.append(f"        {summary(change.new if change.op == '+' else change.old)}")
    if len(changes) > limit:
        lines.append(f"    … {len(changes) - limit} more (--limit to raise)")
    return lines


# ---------------------------------------------------------------------------
# поиск по дереву
# ---------------------------------------------------------------------------
def find_node(tree, node_id):
    """Узел с таким ``id`` и путь до него -- или ``(None, None)``."""
    for path, node in walk(tree):
        if node.get(KEY) == node_id:
            return path, node
    return None, None


def resolve_id(snapshot, value):
    """Номер узла, названный устойчивой своей частью.

    Внутри повторителя номер несёт ключ записи -- ``Tasks.l2#01a0…``, -- а ключи
    выдаются при первом запуске, и в базе, собранной из исходника, они новые
    каждый раз. Устойчива только часть до ``#``, и назвать её должно быть
    достаточно: если под неё подходит ровно один узел, он и имеется в виду.
    Иначе команду нельзя написать в две строки -- номер, увиденный в одном
    запуске, в следующем уже не существует.
    """
    if not value:
        return value
    ids = [node[KEY] for _, node in walk(snapshot)
           if isinstance(node.get(KEY), str)]
    if value in ids:
        return value
    matches = sorted({i for i in ids if i.startswith(value + "#")})
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise SystemExit(
            f"{value!r} names {len(matches)} nodes; say which:\n  "
            + "\n  ".join(matches)
        )
    return value


def resolve_event(event, snapshot):
    """То же для события: ``list_id``/``button_id``/``screen_id`` в нём."""
    out = dict(event)
    for key in ("list_id", "button_id", "screen_id"):
        if isinstance(out.get(key), str):
            out[key] = resolve_id(snapshot, out[key])
    return out


# ---------------------------------------------------------------------------
# дерево экрана
# ---------------------------------------------------------------------------
def _label(node):
    """Одна строка про узел: что это, как называется и чем отличается."""
    kind = node.get("type", "?")
    nid = node.get(KEY, "")
    if kind == "field":
        state = "" if node.get("visible", True) else "  hidden"
        scope = "" if node.get("scope") == "record" else f"  {node.get('scope')}"
        return (f"{kind:<7} {nid:<28} {node.get('name')}: "
                f"{node.get('ftype')}/{node.get('widget')}{scope}{state}")
    if kind == "list":
        more = "+" if node.get("has_more") else ""
        return (f"{kind:<7} {nid:<28} {node.get('model')}  "
                f"{node.get('count')}{more} rows  item={node.get('item')} "
                f"open={node.get('open')}  {node.get('label') or ''}")
    if kind == "button":
        action = (node.get("action") or {}).get("type")
        state = "" if node.get("visible", True) else "  hidden"
        if node.get("enabled") is False:
            state += "  disabled"
        return (f"{kind:<7} {nid:<28} {action}  "
                f"{node.get('label') or node.get('icon') or ''}{state}")
    text = node.get("label") or node.get("value") or ""
    return f"{kind:<7} {nid:<28} {text}"


def render_tree(node, depth=0, rows=5):
    """Экран как дерево узлов, по строке на узел.

    То же, что дают React и Vue DevTools, и по той же причине: дерево -- это то,
    в чём разработчик держит экран, а строки списка -- данные, которых в нём
    ровно столько, сколько записей. Поэтому список показывает число строк, а не
    строки: иначе дерево тонет в них, а вопрос почти всегда о структуре.

    Заодно это единственный удобный способ узнать номер узла: у повторителя он
    содержит ключ записи (``Tasks.l2#01a0…``), и угадать его нельзя.
    """
    pad = "  " * depth
    lines = [pad + _label(node)]
    # Строки -- данные, а не структура: их ключи нужны, чтобы назвать запись в
    # событии (`open`, `write`), а их содержимое -- нет.
    if node.get("type") == "list":
        entries = node.get("rows") or []
        for entry in entries[:rows]:
            lines.append(f"{pad}  row     {entry.get('id')}  {row_label(entry)}")
        if len(entries) > rows:
            lines.append(f"{pad}  row     … {len(entries) - rows} more")
    for child in node.get("children") or []:
        lines.extend(render_tree(child, depth + 1, rows))
    for extra in ("fab", "menu"):
        if isinstance(node.get(extra), dict):
            lines.extend(render_tree(node[extra], depth + 1, rows))
    return lines


def render_screens(snapshot, rows=5):
    """Каждый раздел, каждый его кадр и дерево кадра."""
    lines = []
    for key, frames in snapshot.get("stacks", {}).items():
        mark = "  (active)" if key == snapshot.get("active") else ""
        lines.append(f"{key}{mark}")
        for frame in frames:
            title = frame.get("title")
            record = f"  record={frame['record_id']}" if frame.get("record_id") else ""
            lines.append(f"  {frame['id']}  view {frame['view']}  "
                         f"{title!r}{record}")
            if frame.get("error"):
                lines.append(f"      ! {frame['error']}")
            for child in frame.get("children") or []:
                lines.extend(render_tree(child, depth=2, rows=rows))
            for child in frame.get("navbar_buttons") or []:
                lines.extend(render_tree(child, depth=2, rows=rows))
    return lines


# ---------------------------------------------------------------------------
# запуск приложения
# ---------------------------------------------------------------------------
#: Хост живёт в **привязке на JavaScript**, а не в ядре: он поднимает
#: приложение так же, как это делает устройство. Путь спрашивается у искателя
#: (`oneframework.core`) -- жёсткий разъехался бы молча, когда репозитории
#: разошлись, и `inspect` показывал бы отказ «нет файла» вместо «нет ядра».
def _хост_js():
    return core.файл("src", "inspect-host.mjs")


class JsRuntime:
    """Рантайм на JavaScript, спрошенный из питона.

    Тот же код, что стоит на устройстве: `inspect` больше не поднимает вторую
    реализацию, чтобы посмотреть на первую. Раньше отвечал
    ``oneframework/runtime/session.py, удалён`` -- около 4 200 строк вместе с `rel/`, и
    на устройстве из них не исполнялось ни одной.

    Разговор -- одним заходом на вопрос, а не долгим соединением. События
    копятся и проигрываются с начала каждый раз: рантайм детерминирован, ответ
    от этого не меняется, а держать процесс между вопросами не за чем.
    Отладочная команда может себе позволить лишние миллисекунды на запуск node;
    простота стоит дороже.
    """

    def __init__(self, db_file, screens, models=()):
        self._db = str(db_file)
        self._screens = screens
        self._models = list(models)
        self._events = []
        self._read = None
        self._doc = None
        self._evaluate = None
        self._ответ = self._спросить()

    def _спросить(self):
        ввод = json.dumps({"db": self._db, "screens": self._screens,
                           "events": self._events, "all": self._models,
                           "read": self._read, "doc": self._doc,
                           "evaluate": self._evaluate},
                          ensure_ascii=False, default=str)
        готово = subprocess.run([core.node(), str(_хост_js())], input=ввод,
                                capture_output=True, text=True, encoding="utf-8")
        if готово.returncode != 0:
            raise OneFrameworkError(
                "Рантайм на JS не ответил. Для `inspect` нужен node: рантайма на "
                f"питоне у нас больше нет.\n{готово.stderr.strip()[:400]}")
        ответ = json.loads(готово.stdout)
        if "error" in ответ:
            # След JS -- не то, что спрашивали. Отказ рантайма («неизвестный
            # список») человек читает как ответ, и четыре строки чужих кадров
            # под ним делают ответ незаметным. Кому нужен след -- у того есть
            # `node libs/js/src/inspect-host.mjs`.
            слово = str(ответ["error"]).removeprefix("Error: ")
            raise OneFrameworkError(слово)
        return ответ

    def snapshot(self):
        """Последний кадр -- после всех посланных событий."""
        события = self._ответ.get("events") or []
        return события[-1]["snapshot"] if события else self._ответ["snapshot"]

    def dispatch(self, event):
        self._events.append(event)
        self._ответ = self._спросить()
        return self.snapshot()

    def screen_by_id(self, screen_id):
        """Не кадр рантайма, а то единственное, что у него здесь спрашивают."""
        состояние = (self._ответ.get("state") or {}).get(screen_id)
        return None if состояние is None else _Состояние(состояние)

    @property
    def counts(self):
        return self._ответ.get("counts") or {}

    def all(self, model_name):
        """Все записи модели -- у той же базы, что считает кадр.

        Питоновского читателя у `inspect` больше нет: вторая реализация доступа
        к SQLite ушла вместе с рантаймом. Файл при этом тот же самый -- копия во
        временном каталоге.
        """
        return (self._ответ.get("all") or {}).get(model_name) or []

    def read(self, model_name, record_id):
        """Одна запись. Спрашивается отдельным заходом: `--why` зовёт это раз."""
        self._read = [model_name, record_id]
        try:
            return self._спросить().get("read")
        finally:
            self._read = None

    @property
    def defs(self):
        return self._ответ.get("defs") or []

    def evaluate(self, узлы):
        """Чем оказались поддеревья условия -- у того вычислителя, что решал.

        Пачкой, а не по одному: `--why` спрашивает про всё дерево сразу, и
        заход на каждое поддерево стоил бы запуска node на каждый узел.
        """
        self._evaluate = узлы
        try:
            return [о.get("ok") for о in self._спросить().get("evaluate") or []]
        finally:
            self._evaluate = None

    def doc(self, kind, name):
        """Документ **как он лежит в базе** -- не как его собирает исходник.

        Разница между этими двумя и есть ответ на «почему на устройстве не тот
        экран», поэтому спрашивать надо именно базу.
        """
        self._doc = [kind, name]
        try:
            return self._спросить().get("doc")
        finally:
            self._doc = None


class _Состояние:
    """Ровно один метод: `inspect` больше от кадра ничего не хочет."""

    def __init__(self, значения):
        self._значения = значения

    def state_values(self):
        return self._значения


class Opened:
    """Запущенное приложение и всё, что понадобится, чтобы его разглядывать."""

    def __init__(self, app, runtime, source, tmpdir=None, stale=None):
        self.app = app
        self.rt = runtime
        #: откуда взялась база -- строкой, для шапки
        self.source = source
        self.tmpdir = tmpdir
        #: определения, которые лежали в открытом файле и разошлись с тем, что
        #: собирает исходник прямо сейчас: ``{(kind, name): старый отпечаток}``
        self.stale = stale or {}

    #: Записи читаются у рантайма: он открыл ту же базу, и второго читателя
    #: SQLite у питона нет с 21.08.2026.
    @property
    def db(self):
        return self.rt

    def close(self):
        if self.tmpdir is not None:
            shutil.rmtree(self.tmpdir, ignore_errors=True)


def _seed_beside(app_file: Path):
    """``seed.py`` рядом с приложением -- ровно как его берёт браузерный мост."""
    path = app_file.parent / "seed.py"
    if not path.exists():
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"_inspect_seed_{path.parent.name}", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return getattr(module, "seed", None)


def _build_into(app, app_file: Path, path: Path):
    """Собрать базу приложения в файл -- схема, определения, seed.

    Тем же сборщиком, что у ``oneframework build``: питон говорит, что класть,
    кладёт `libs/js/src/build-db.mjs`. Своего писателя SQLite у питона больше
    нет -- две реализации одного формата расходились молча.

    Файл может уже существовать: ``--db FILE`` выкладывает приложение поверх
    базы, которая у пользователя есть, и определения в ней надо обновить, а не
    потерять вместе с данными.
    """
    from .assets import write_app_db

    path.parent.mkdir(parents=True, exist_ok=True)
    write_app_db(app, _seed_beside(app_file), path, поверх=True)


def open_app(app_file: Path, db_file=None) -> Opened:
    """Поднять приложение так же, как его поднимает устройство.

    Без ``--db`` база собирается из исходника вместе с seed-ами -- это те же
    данные, которые увидит пользователь при первом запуске, а не пустой файл.
    Но ключи записей выдаются посевом, поэтому в такой базе они новые на каждый
    запуск, и событие, называющее запись, написать невозможно. Поэтому
    ``--db FILE`` не только открывает существующий файл, но и **создаёт** его,
    если файла нет: со второго запуска ключи держатся.

    Открывается всегда копия: смотреть приходится в тот файл, которым
    пользуется приложение, а посланное для проверки событие -- это запись.

    Своего доступа к SQLite у питона здесь больше нет. Базу пишет тот же
    сборщик, что у ``oneframework build``, читает тот же рантайм, что стоит на
    устройстве. Вторая реализация доступа расходилась бы с первой молча.
    """
    from .main import load_app

    app = load_app(app_file)
    tmpdir = tempfile.mkdtemp(prefix="oneframework-inspect-")
    файл = Path(tmpdir) / "app.db"
    stale = {}

    if db_file is None:
        source = "built from source + seeds (in memory; record keys are new each run)"
    else:
        origin = Path(db_file).resolve()
        created = not origin.exists()
        if created:
            _build_into(app, app_file, origin)
        shutil.copyfile(origin, файл)
        # Что лежало в файле -- до того, как выкладка перезапишет определения
        # тем, что собирает исходник. Расхождение здесь и есть ответ на «почему
        # на устройстве не тот экран».
        stale = {(d["kind"], d["name"]): d["fingerprint"]
                 for d in JsRuntime(файл, []).defs}
        size = origin.stat().st_size
        note = "created" if created else "working on a copy"
        source = f"{origin} ({size // 1024} KB, {note})"

    # Определения и seed-ы кладёт в базу выкладка -- она же и на сборке.
    # Считает по ним кадр рантайм на JS, тем же кодом, что на устройстве.
    _build_into(app, app_file, файл)
    runtime = JsRuntime(файл, [s.ir() for s in app.screens],
                        models=[m.__name__ for m in app.models])

    if stale:
        now = {(d["kind"], d["name"]): d["fingerprint"] for d in runtime.defs}
        stale = {k: v for k, v in stale.items() if now.get(k) != v}
    return Opened(app, runtime, source, tmpdir=tmpdir, stale=stale)


# ---------------------------------------------------------------------------
# отдельные разделы вывода
# ---------------------------------------------------------------------------
def def_rows(rt):
    """Определения из базы: вид, имя, отпечаток, ревизия и настоящий размер.

    Спрашиваются у рантайма: он открыл ту же базу, а второго читателя SQLite у
    питона нет с 21.08.2026.
    """
    return sorted(rt.defs, key=lambda r: (r["kind"], r["name"]))


def overview(opened: Opened, app_file: Path):
    """Всё приложение одним экраном -- плоским перечнем, который можно grep-нуть.

    Взято у ``rails routes``: ценность списка не в красоте, а в том, что он
    полон и плоск. Разделы, модели, определения -- по строке на каждое, и
    отпечаток рядом с именем, потому что вопрос «то ли это определение, что на
    устройстве» задаётся чаще любого другого.
    """
    app, db = opened.app, opened.db
    out = [f"{app.title}   {app_file}", f"data     {opened.source}", ""]

    out.append("screens")
    for screen in app.screens:
        label = screen.label or ""
        out.append(f"  {screen.key:<16} {screen.view.__name__:<20} {label}")

    out.append("")
    out.append("models")
    for model in app.models:
        names = ", ".join(n for n, f in model._fields.items() if not f.system)
        out.append(f"  {model.__name__:<16} {model._table:<20} "
                   f"{opened.rt.counts.get(model.__name__, 0):>6} rows   {names}")

    out.append("")
    out.append(f"definitions      {'fingerprint':<18} {'rev':>3} {'bytes':>7}")
    total = 0
    for row in def_rows(opened.rt):
        total += row["bytes"]
        mark = " *stale on device" if (row["kind"], row["name"]) in opened.stale else ""
        out.append(f"  {row['kind']:<6} {row['name']:<16} {row['fingerprint']:<18} "
                   f"{row['revision']:>3} {row['bytes']:>7}{mark}")
    out.append(f"  {'':<6} {'':<16} {'':<18} {'':>3} {total:>7}  total")

    if opened.stale:
        out.append("")
        out.append(f"  * {len(opened.stale)} definition(s) in that file differ from what "
                   "this source builds now")

    skipped = defs.SKIPPED
    if skipped:
        out.append("")
        out.append("views with no document (still programs, not data)")
        for name, reason in skipped.items():
            out.append(f"  {name:<16} {reason}")

    out.append("")
    out.append("the database is a plain SQLite file -- for tables, queries and")
    out.append("browsing use `sqlite3` or `datasette`; this command does not repeat them")
    return out


def show_model(app, name):
    """Схема модели: то же, что уезжает в базу, плюс то, что видно только тут."""
    from ..model.fields import Many2one
    from ..model.schema import model_schema

    model = next((m for m in app.models if m.__name__ == name), None)
    if model is None:
        raise SystemExit(
            f"Unknown model {name!r}. Available: "
            + ", ".join(m.__name__ for m in app.models)
        )
    doc = model_schema(model)
    display = model.display_field()
    for entry in doc["fields"]:
        field = model._fields[entry["name"]]
        entry["label"] = field.display_label
        entry["widget"] = field.default_widget
        entry["widgets"] = list(field.widgets)
        entry["system"] = bool(field.system)
        entry["display_field"] = display is not None and display.name == entry["name"]
        if isinstance(field, Many2one):
            entry["comodel"] = field.resolve_comodel().__name__
    return doc


def show_view(app, name):
    view = next((v for v in app.views if v.__name__ == name), None)
    if view is None:
        raise SystemExit(
            f"Unknown view {name!r}. Available: "
            + ", ".join(v.__name__ for v in app.views)
        )
    return document(view)


def where(app, node_id):
    """Какой вид объявляет этот узел -- и виден ли он сейчас на экране.

    Первый вопрос отладки в Odoo: «какой вид отвечает за то, что я вижу». Здесь
    он дешевле, чем там: номер узла содержит имя вида, но подтверждается по
    документу, и заодно достаётся само объявление -- условие видимости,
    виджет, домен, -- то есть причина, по которой узел выглядит так.
    """
    out = []
    for view in app.views:
        try:
            doc = document(view)
        except Exception:
            continue
        path, node = find_node(doc, node_id)
        if node is not None:
            out.append({"view": view.__name__, "path": path, "node": node})
    return out


def shell_namespace(opened: Opened):
    """Что должно быть под рукой в консоли, без единого импорта.

    Приём ``shell_plus``: ценность консоли не в консоли, а в том, что в ней уже
    всё разложено. Читать записи -- через ``db``: ``Model.get``/``Model.all``
    читали через питоновский рантайм и ушли вместе с ним.
    """
    space = {m.__name__: m for m in opened.app.models}
    space.update({v.__name__: v for v in opened.app.views})
    space.update(app=opened.app, rt=opened.rt, db=opened.db,
                 document=document, defs=defs, diff=diff, snapshot=opened.rt.snapshot)
    return space


def shell(opened: Opened):
    import code

    try:  # стрелка вверх в консоли -- не роскошь
        import readline  # noqa: F401
    except ImportError:
        pass

    space = shell_namespace(opened)
    models = [m.__name__ for m in opened.app.models]
    one = models[0] if models else "Model"
    code.interact(
        banner=(
            f"oneframework shell -- {opened.app.title}\n"
            f"  models    {', '.join(models)}   (db.read({one}, id), db.all({one}))\n"
            "  app, rt, db, snapshot(), document(View), defs, diff(a, b)\n"
        ),
        local=space,
        exitmsg="",
    )


# ---------------------------------------------------------------------------
# почему узел выглядит так
# ---------------------------------------------------------------------------
#: Как читается операция условия, когда её показывают человеку.
_OPS = {"&": "and", "|": "or", "!": "not", "null": "is null"}


def _поддеревья(node, out=None):
    """Все узлы условия сверху вниз -- чтобы спросить о них одним заходом."""
    out = [] if out is None else out
    out.append(node)
    if isinstance(node, dict):
        части = node.get("p")
        if части is None:
            части = [node[k] for k in ("e", "l", "r") if k in node and "op" in node]
        for ч in части or ():
            _поддеревья(ч, out)
    return out


def _значения(rt, node, row, view_state):
    """Чем оказалось каждое поддерево -- **у того вычислителя, что решал**.

    До 21.08.2026 объяснял питоновский вычислитель, а решал тот, что на
    устройстве. Расходились они на пропущенном ключе записи: у устройства он
    значит «не выбрано» и расширяет условие. Объяснение не тем вычислителем --
    худший род объяснения: оно выглядит ответом.

    Одним заходом на всё дерево: заход стоит запуска node, а узлов в дереве
    десятки.
    """
    узлы = _поддеревья(node)
    спросить = [у for у in узлы if not _само_значение(у)]
    ответы = dict(zip(map(id, спросить), rt.evaluate(
        [[у, row, view_state] for у in спросить]))) if спросить else {}
    return {id(у): (_само_значение(у) if _само_значение(у) is not None
                    else ответы.get(id(у))) for у in узлы}


def _само_значение(node):
    """Ссылка -- это значение, а не истинность: показать 0 полезнее, чем False."""
    if not isinstance(node, dict):
        return None
    if "r" in node and "op" not in node:
        return _ЗНАЧЕНИЕ_ЗАПИСИ
    if "v" in node:
        return _ЗНАЧЕНИЕ_ВИДА
    if "i" in node:
        return "(row of a repeat)"
    return None


_ЗНАЧЕНИЕ_ЗАПИСИ = object()
_ЗНАЧЕНИЕ_ВИДА = object()


def _expr_value(node, row, view_state, значения=None):
    """Чем одно поддерево условия оказалось на этой записи."""
    сам = _само_значение(node)
    if сам is _ЗНАЧЕНИЕ_ЗАПИСИ:
        return row.get(node["r"])
    if сам is _ЗНАЧЕНИЕ_ВИДА:
        return view_state.get(node["v"], "(unset)")
    if сам is not None:
        return сам
    return (значения or {}).get(id(node))


def _expr_label(node):
    if not isinstance(node, dict):
        return json.dumps(node, ensure_ascii=False)
    if "r" in node and "op" not in node:
        return f"record.{node['r']}"
    if "v" in node:
        return f"view.{node['v']}"
    if "i" in node:
        return f"item.{node['i']}"
    op = node.get("op")
    if op in _OPS:
        return _OPS[op]
    if op:
        return op
    return brief(node)


def _decides(node, values):
    """Какая часть решила исход: первая ложная в ``and``, первая истинная в ``or``.

    То же, что показывает отладчик потока в Salesforce: ветку, которая была
    взята. Без неё условие из пяти частей приходится проверять целиком глазами.
    """
    op = node.get("op")
    if op == "&":
        return next((i for i, v in enumerate(values) if v is False), None)
    if op == "|":
        return next((i for i, v in enumerate(values) if v is True), None)
    return None


def explain_expr(node, row, view_state, depth=0, значения=None):
    """Условие как дерево, и у каждой ветки -- чем она оказалась."""
    value = _expr_value(node, row, view_state, значения)
    lines = [f"{'  ' * depth}{_expr_label(node):<40} {brief(value, 24)}"]
    if not isinstance(node, dict):
        return lines
    parts = node.get("p")
    if parts is None:
        for key in ("e", "l", "r"):
            if key in node and "op" in node:
                parts = (parts or []) + [node[key]]
    if not parts:
        return lines
    values = [_expr_value(p, row, view_state, значения) for p in parts]
    chosen = _decides(node, values)
    for i, part in enumerate(parts):
        sub = explain_expr(part, row, view_state, depth + 1, значения)
        if i == chosen:
            sub[0] += "   <- decides"
        lines.extend(sub)
    return lines


def why(app, rt, db, node_id, record_id=None):
    """Почему узел на экране выглядит так, как выглядит.

    Единственная поверхность здесь, которой нет ни у ``sqlite3``, ни у
    Datasette: чтобы её дать, надо истолковать определение на данных. Odoo в
    подсказке к полю показывает объявленное ``Invisible: <выражение>`` и на
    этом останавливается -- а вопрос почти всегда не «какое условие», а «что
    оно дало на этой записи».
    """
    snapshot = rt.snapshot()
    # Один вид рисует все строки списка, поэтому номер узла в них общий, и
    # занятий у него столько же, сколько записей. Спрашивают всегда про одну.
    drawn = [(p, n) for p, n in walk(snapshot) if n.get(KEY) == node_id]
    if not drawn:
        raise SystemExit(f"No node {node_id!r} on screen.")

    # Узел внутри строки списка нарисован по разу на запись, но на проводе он
    # один: описание строки едет однажды, а ответы лежат в ``rows[i].v``.
    # Значит и запись, и вычисленное значение берутся оттуда, а не с узла.
    lists, entry = rows_of(snapshot, node_id), None
    if lists:
        holder = None
        if record_id is not None:
            holder = next(
                (lst for lst in lists
                 if any(r.get("id") == record_id for r in lst.get("rows") or ())),
                None,
            )
            if holder is None:
                raise SystemExit(
                    f"{node_id} is not drawn for record {record_id!r}.")
            entry = next(r for r in holder["rows"] if r["id"] == record_id)
        else:
            holder = next((lst for lst in lists if lst.get("rows")), lists[0])
            rows = holder.get("rows") or []
            entry = rows[0] if rows else None
        drawn = [(p, n) for p, n in drawn
                 if any(x is n for _, x in walk(holder.get("row") or {}))]
    picked = None
    if record_id is not None and not lists:
        picked = next(
            (
                (p, n) for p, n in drawn
                if record_id in (n.get("record_id"),
                                 (n.get("context") or {}).get("record_id"))
            ),
            None,
        )
        if picked is None:
            raise SystemExit(f"{node_id} is not drawn for record {record_id!r}.")
    path, node = picked or drawn[0]
    ctx = node.get("context") or {}
    screen_id = node.get("screen_id") or ctx.get("screen_id")
    frame = rt.screen_by_id(screen_id) if screen_id else None
    view_state = frame.state_values() if frame is not None else {}
    model_name = node.get("model") or ctx.get("model")
    record_id = node.get("record_id") or ctx.get("record_id")
    if entry is not None:
        record_id = entry.get("id") or record_id
        model_name = model_name or (lists[0].get("model") if lists else None)
    row = {}
    if model_name and record_id:
        # Запись читается у рантайма: он открыл ту же базу, и второго читателя
        # SQLite у питона нет.
        row = db.read(model_name, record_id) or {}

    out = [f"{node_id}  at {path}"]
    times = sum(len(lst.get("rows") or []) for lst in lists) if lists else len(drawn)
    if times > 1:
        out.append(f"drawn {times} times (one per row); "
                   "--record ID picks another")
    if row:
        out.append(f"drawn for {model_name} {record_id}  "
                   f"{app.model_by_name(model_name).display_name(row)!r}")
    if view_state:
        out.append("view state  " + brief({k: v for k, v in view_state.items()}, 90))

    for hit in where(app, node_id):
        out.append(f"declared in view {hit['view']} at {hit['path']}")
        for key in ("visible", "enabled"):
            declared = hit["node"].get(key)
            if declared is None:
                continue
            # Ответ на условие внутри строки лежит не на узле, а в векторе
            # значений: узел говорит, из какого гнезда его взять (``bind``).
            effective = node.get(key)
            slot = (node.get("bind") or {}).get(key)
            if slot is not None and entry is not None:
                values = entry.get("v") or []
                if slot < len(values):
                    effective = values[slot]
            if not isinstance(declared, dict):
                out.append(f"  {key} = {json.dumps(declared)}   (not a condition)")
                continue
            out.append(f"  {key} -> {json.dumps(effective)}")
            значения = _значения(rt, declared, row, view_state)
            out.extend("    " + line
                       for line in explain_expr(declared, row, view_state, 0, значения))
    return out


def refs(app, name):
    """Где поле вообще упоминается -- по всем документам видов.

    Обратный указатель: «что сломается, если это поле убрать». Datasette ходит
    по настоящим внешним ключам и дала бы это даром -- но ссылка на поле лежит
    **внутри** документа вида, в его условиях и доменах, куда граф ключей не
    достаёт. Поэтому только это здесь и делается, а не связи между таблицами.
    """
    # ``Task.done`` и ``done`` ищут одно и то же: в документе у ссылки нет
    # модели -- её задаёт то место, где ссылка стоит (список, строка, форма).
    _, _, field = name.rpartition(".")
    out = []
    for view in app.views:
        try:
            doc = document(view)
        except Exception:
            continue
        for path, node in walk(doc):
            if node.get("type") == "field" and node.get("name") == field:
                what = f"drawn as {node.get('widget')}"
            elif set(node) == {"r"} and node["r"] == field:
                what = "read by a condition"
            else:
                continue
            out.append({"view": view.__name__, "path": path, "what": what})
    return out


def export_case(opened: Opened, events, snapshots):
    """Случай для второго рантайма: определения + данные -> ожидаемое дерево.

    Ровно тот вход, который читает ``tests/parity/session_driver.mjs``, плюс
    ожидаемые снимки. Ошибка, найденная здесь, уезжает к рантайму на JS
    воспроизводимым файлом, а не пересказом.
    """
    from ..model.schema import app_schema

    app, db = opened.app, opened.db
    documents = {}
    for view in app.views:
        try:
            documents[view.__name__] = document(view)
        except Exception:
            continue
    return {
        "schema": app_schema(app),
        "models": [m.__name__ for m in app.models],
        "documents": documents,
        "screens": [
            {"key": s.key, "label": s.label, "icon": s.icon, "view": s.view.__name__}
            for s in app.screens
        ],
        "rows": {m.__name__: opened.rt.all(m.__name__) for m in app.models},
        "events": events,
        "expected": {
            "snapshot": snapshots[0],
            "events": [
                {"event": ev, "snapshot": snap}
                for ev, snap in zip(events, snapshots[1:])
            ],
        },
    }


# ---------------------------------------------------------------------------
# команда
# ---------------------------------------------------------------------------
def _load_events(args):
    events = []
    for raw in args.event or []:
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--event is not JSON: {exc}\n  got: {raw}") from None
    if args.replay:
        text = Path(args.replay).read_text(encoding="utf-8").strip()
        if not text:
            return events
        if text.lstrip().startswith("["):
            events.extend(json.loads(text))
        else:  # по событию в строке -- как пишет журнал
            events.extend(json.loads(line) for line in text.splitlines() if line.strip())
    return events


def _dump(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def cmd_inspect(args):
    app_file = Path(args.app).resolve()
    opened = open_app(app_file, args.db)
    try:
        return _inspect(args, opened, app_file)
    finally:
        opened.close()


def _inspect(args, opened: Opened, app_file: Path):
    app, rt = opened.app, opened.rt
    asked = False

    if args.model:
        asked = True
        _dump(show_model(app, args.model))

    if args.view:
        asked = True
        _dump(show_view(app, args.view))

    if args.where:
        asked = True
        found = where(app, args.where)
        if args.json:
            _dump(found)
        elif not found:
            print(f"{args.where}: no view declares this node")
        else:
            for hit in found:
                print(f"{args.where}  declared in view {hit['view']}  at {hit['path']}")
                print(json.dumps(hit["node"], ensure_ascii=False, indent=2)[:2000])
        # ...и где он сейчас нарисован, если нарисован
        path, _node = find_node(rt.snapshot(), args.where)
        if path and not args.json:
            print(f"{args.where}  on screen now at {path}")

    if args.refs:
        asked = True
        found = refs(app, args.refs)
        if args.json:
            _dump(found)
        elif not found:
            print(f"{args.refs}: no view mentions it")
        else:
            for hit in found:
                print(f"{hit['view']:<20} {hit['what']:<22} {hit['path']}")

    events = _load_events(args)
    snapshots = [rt.snapshot()]
    if events:
        asked = True
        for i, event in enumerate(events, 1):
            event = resolve_event(event, snapshots[-1])
            head = f"event {i}: " + brief(event, 100)
            try:
                after = rt.dispatch(event)
            except OneFrameworkError as exc:
                print(head)
                print(f"    ! {type(exc).__name__}: {exc}")
                return 1
            changes = diff(comparable(snapshots[-1]), comparable(after))
            snapshots.append(after)
            if args.json:
                _dump({"event": event,
                       "changes": [c._asdict() for c in changes]})
            else:
                print(head)
                print("\n".join(format_diff(changes, limit=args.limit)))

    # После событий, а не до: спрашивают обычно «почему после нажатия так».
    if args.why:
        asked = True
        node_id = resolve_id(snapshots[-1], args.why)
        print("\n".join(why(app, rt, opened.db, node_id, record_id=args.record)))

    if args.tree is not None:
        asked = True
        snapshot = snapshots[-1]
        if args.tree:
            _, node = find_node(snapshot, resolve_id(snapshot, args.tree))
            if node is None:
                raise SystemExit(f"No node {args.tree!r} on screen.")
            print("\n".join(render_tree(node, rows=args.rows)))
        else:
            print("\n".join(render_screens(snapshot, rows=args.rows)))

    if args.screen is not None:
        asked = True
        snapshot = snapshots[-1]
        if args.screen:
            path, node = find_node(snapshot, resolve_id(snapshot, args.screen))
            if node is None:
                raise SystemExit(
                    f"No node {args.screen!r} on screen. Node ids are shown by "
                    "`--screen` and start with the view name, e.g. 'Tasks.l1'."
                )
            print(f"// {path}")
            _dump(node)
        else:
            _dump(displayable(snapshot))

    if args.export:
        asked = True
        case = export_case(opened, events, snapshots)
        Path(args.export).write_text(
            json.dumps(case, ensure_ascii=False, default=str), encoding="utf-8"
        )
        print(f"wrote {args.export}: {len(case['documents'])} documents, "
              f"{sum(len(r) for r in case['rows'].values())} rows, "
              f"{len(events)} event(s)")
        print("replay it against the JS runtime with:")
        print(f"  node tests/parity/session_driver.mjs < {args.export}")

    if args.defs:
        asked = True
        rows = def_rows(opened.rt)
        if args.json:
            _dump(rows)
        else:
            for row in rows:
                mark = " *stale" if (row["kind"], row["name"]) in opened.stale else ""
                print(f"{row['kind']:<6} {row['name']:<20} {row['fingerprint']}  "
                      f"r{row['revision']:<3} {row['bytes']:>7} B{mark}")

    if args.shell:
        asked = True
        shell(opened)

    if not asked:
        print("\n".join(overview(opened, app_file)))
    return 0


def add_parser(sub):
    """Подключить команду к разбору аргументов ``oneframework``."""
    p = sub.add_parser(
        "inspect",
        help="look at an app without a browser: documents, screen, events",
        description=(
            "Show what an app is made of and what one event does to it. "
            "With no options: an overview. The database is plain SQLite -- "
            "use sqlite3 or datasette for arbitrary queries."
        ),
    )
    p.add_argument("app", help="path to your app.py")
    p.add_argument("--db", metavar="FILE",
                   help="work on a real database, created if absent; record keys "
                        "then stay put between runs. Always a copy -- the file "
                        "itself is never written to")
    p.add_argument("--model", metavar="NAME", help="print a model's schema")
    p.add_argument("--view", metavar="NAME", help="print a view's document")
    p.add_argument("--tree", nargs="?", const="", metavar="NODE",
                   help="the screen as a node tree, one line per node -- start here")
    p.add_argument("--screen", nargs="?", const="", metavar="NODE",
                   help="print the current snapshot as JSON, whole or under NODE")
    p.add_argument("--event", action="append", metavar="JSON",
                   help="dispatch an event and print the diff; repeatable")
    p.add_argument("--replay", metavar="FILE",
                   help="dispatch a recorded sequence (JSON array or one per line)")
    p.add_argument("--where", metavar="NODE",
                   help="which view declares this node, and what it declares")
    p.add_argument("--why", metavar="NODE",
                   help="why it looks like that: its conditions evaluated on its record")
    p.add_argument("--record", metavar="ID",
                   help="--why: which row's copy of that node to explain")
    p.add_argument("--refs", metavar="[MODEL.]FIELD",
                   help="every view node and condition that mentions this field")
    p.add_argument("--shell", action="store_true",
                   help="a Python prompt with the app running and its models loaded")
    p.add_argument("--defs", action="store_true",
                   help="list the definitions in the database with fingerprints and sizes")
    p.add_argument("--export", metavar="FILE",
                   help="write definitions + data + expected trees as a replayable case")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--limit", type=int, default=60, help="max diff lines per event")
    p.add_argument("--rows", type=int, default=5, help="row ids shown per list in --tree")
    p.set_defaults(func=cmd_inspect)
    return p
