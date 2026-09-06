import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

КОМАНДА = ROOT / "bin" / "oneframework.mjs"

#: Ядро зовётся отсюда, а не из привязки.
def _ядро(*части) -> Path:
    return ROOT.joinpath("libs", "js", *части)

def собрать_базу(пакет, куда, поверх=False):
    узел = shutil.which("node")
    if узел is None:
        pytest.skip("node на этой машине нет")
    куда = Path(куда)
    if not поверх and куда.exists():
        куда.unlink()
    док = dict(пакет.doc if hasattr(пакет, "doc") else пакет)
    док["file"] = str(куда)
    готово = subprocess.run([узел, str(_ядро("src", "build-db.mjs"))],
                            input=json.dumps(док, ensure_ascii=False, default=str),
                            capture_output=True, text=True, encoding="utf-8",
                            cwd=str(ROOT))
    if готово.returncode != 0:
        raise ОтказЯдра(f"сборщик базы не запустился:\n{готово.stderr}")
    ответ = json.loads(готово.stdout)
    if "error" in ответ:
        raise ОтказЯдра(f"сборщик базы отказал: {ответ['error']}")
    return куда

def объявить(приложение) -> dict:
    узел = shutil.which("node")
    if узел is None:
        pytest.skip("node на этой машине нет")
    готово = subprocess.run([узел, str(КОМАНДА), "declare", str(приложение)],
                            capture_output=True, text=True, cwd=str(ROOT))
    assert готово.returncode == 0, f"{приложение}: {готово.stderr}"
    return json.loads(готово.stdout)

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples" / "todo"))

@pytest.fixture()
def todo_app():
    """The exact acceptance-criterion app from examples/todo/app.py."""
    import app as todo_module

    return todo_module

#: Фикстура ``db`` жила здесь и отдавала питоновскую базу.

#: Фикстура ``runtime`` жила здесь и поднимала питоновский рантайм.

#: Половина рантайма переехала на JS, и проверять её можно только запустив.
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node недоступен")

ЯДРО_РЯДОМ = (ROOT / "libs" / "js" / "src").is_dir()

нужно_ядро = pytest.mark.skipif(
    not ЯДРО_РЯДОМ,
    reason="ядра нет рядом: проверка про привязку, но обстановку ей даёт ядро")

def run_node(tmp_path, script, payload):
    data = tmp_path / "payload.json"
    data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    runner = tmp_path / "run.mjs"
    runner.write_text(script, encoding="utf-8")

    done = subprocess.run(
        ["node", str(runner), str(data)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert done.returncode == 0, done.stderr
    return done.stdout

def flat(nodes):
    for node in nodes:
        yield node
        if node.get("children"):
            yield from flat(node["children"])

def the_list(runtime):
    tree = runtime.stack[-1].tree
    return next(c for c in tree["children"] if c["type"] == "list")

def bind_row(node, row):
    doc = node["row"]
    values = row["v"]

    def bind(n):
        out = dict(n)
        slots = out.pop("bind", None)
        if out.get("children") is not None:
            out["children"] = [bind(c) for c in out["children"]]
        if slots:
            for key, index in slots.items():
                out[key] = values[index]
        if out.get("type") == "field":
            if out.get("scope") == "record":
                out["record_id"] = row["id"]
                if out.get("ftype") in ("many2one", "one2one"):
                    out["related"] = next(
                        (c for c in out.get("choices") or () if c["id"] == out.get("value")),
                        None,
                    )
        elif out.get("type") == "button":
            out["context"] = {**out["context"], "record_id": row["id"]}
        return out

    entry = {
        "id": row["id"],
        "openable": doc["openable"],
        "children": [bind(c) for c in doc["children"]],
    }
    if doc.get("cells"):
        entry["cells"] = [bind(c) for c in doc["cells"]]
    return entry

def bound_rows(node):
    return [bind_row(node, row) for row in node.get("rows") or ()]

def titles(runtime):
    node = the_list(runtime)
    return [
        next(c for c in flat(row["children"]) if c.get("name") == "text")["value"]
        for row in bound_rows(node)
    ]

#: Спрашивать про Kotlin надо у **ядра**: там живёт единственная реализация
#: поиска компилятора и кэша TeaVM (`libs/js/src/build/`).
_ЯДРО_KOTLIN = ROOT / "libs" / "js" / "src" / "build" / "kotlin.mjs"
_ЯДРО_TEAVM = ROOT / "libs" / "js" / "src" / "build" / "teavm.mjs"
_ОСНАСТКА = {}

def _спросить_ядро():
    if "ответ" not in _ОСНАСТКА:
        скрипт = (
            "import { kotlinCompiler, home } from " + json.dumps(str(_ЯДРО_TEAVM)) + ";\n"
            "let есть = null;\n"
            "try { есть = kotlinCompiler(); } catch { есть = null; }\n"
            'process.stdout.write(JSON.stringify({ compiler: есть, home: home() }));'
        )
        готово = subprocess.run(
            [shutil.which("node") or "node", "--input-type=module", "-e", скрипт],
            capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
        _ОСНАСТКА["ответ"] = (json.loads(готово.stdout) if готово.returncode == 0
                              else {"compiler": None, "home": None})
    return _ОСНАСТКА["ответ"]

def kotlin_ready() -> bool:
    return _спросить_ядро()["compiler"] is not None

def teavm_home() -> str:
    return _спросить_ядро()["home"]

needs_kotlin = pytest.mark.skipif(not kotlin_ready(), reason="компилятора Kotlin нет")

def план(пакет):
    доc = getattr(пакет, "doc", пакет)
    скрипт = (
        "import { readFileSync } from 'node:fs';\n"
        "import { buildPlan } from " + json.dumps(str(
            ROOT / "libs" / "js" / "src" / "build" / "plan.mjs")) + ";\n"
        "process.stdout.write(JSON.stringify("
        "buildPlan(JSON.parse(readFileSync(process.argv[1], 'utf8')))));"
    )
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as ф:
        json.dump(доc, ф, ensure_ascii=False, default=str)
        путь = ф.name
    готово = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", скрипт, путь],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
    if готово.returncode != 0:
        raise ОтказЯдра(готово.stderr.strip())
    return json.loads(готово.stdout)

class ОтказЯдра(RuntimeError):
    """Ядро отказалось строить план. Слова его, не наши."""
