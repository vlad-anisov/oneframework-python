"""Module loading.

An application is a directory of modules. A module is just a folder with an
``__init__.py``; there is no manifest, no install state and no dependency
graph to maintain. If the folder is there, the module is part of the app.

    myapp/
        contacts/
            __init__.py         imports its own models and views
            models.py
            views.py
            seed.py             optional: demo data, run once
            static/widgets.js   optional: custom JS widgets
        invoices/
            __init__.py
        app.py                  App(root_view=...) or App(modules=...)

Load order is alphabetical unless a module declares ``DEPENDS``, in which case
its dependencies are loaded first. That is the only ordering concept -- enough
for one module to extend another's models, and small enough to explain in a
sentence.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

from .errors import OneFrameworkError

__all__ = ["Module", "discover", "load_all", "MODULES"]

#: Every loaded module, by name, in load order.
MODULES: dict[str, "Module"] = {}


class Module:
    """One loaded module."""

    def __init__(self, name, path, package):
        self.name = name
        self.path = Path(path)
        self.package = package

    @property
    def depends(self):
        return tuple(getattr(self.package, "DEPENDS", ()) or ())

    @property
    def seed(self):
        """``seed(db)`` from ``seed.py``, if the module ships one."""
        try:
            mod = importlib.import_module(f"{self.package.__name__}.seed")
        except ModuleNotFoundError:
            return None
        return getattr(mod, "seed", None)

    @property
    def logic(self):
        """``LOGIC`` из ``__init__.py``: скомпилированные модули и их действия.

        Объявляется там же, где ``DEPENDS``, и по той же причине: у модуля нет
        файла-манифеста и заводить его ради одного списка не стоит. Форма::

            LOGIC = [{"module": "logic/tasks.wasm", "language": "rust",
                      "actions": [{"name": "Task.complete", ...}]}]

        Путь -- относительно папки модуля.
        """
        out = []
        for entry in getattr(self.package, "LOGIC", ()) or ():
            entry = dict(entry)
            # Запись без ``module`` -- действия, объявленные **данными**:
            # правило плюс правка, без единого байта кода. Пути у них нет и
            # быть не может.
            if entry.get("module"):
                entry["path"] = (self.path / entry["module"]).resolve()
            out.append(entry)
        return out

    def static_files(self, suffix=".js"):
        """Files under ``static/`` the host should load (custom widgets)."""
        static = self.path / "static"
        if not static.is_dir():
            return []
        return sorted(p for p in static.rglob(f"*{suffix}") if p.is_file())

    def __repr__(self):
        return f"<Module {self.name}>"


def discover(root) -> list[str]:
    """Names of the module folders directly under *root*.

    A folder counts when it holds an ``__init__.py``. Anything else -- caches,
    notes, a stray virtualenv -- is ignored, so "the folder is there" really is
    the whole rule.
    """
    root = Path(root)
    if not root.is_dir():
        raise OneFrameworkError(f"Module directory not found: {root}")
    names = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith((".", "_")):
            continue
        if (entry / "__init__.py").exists():
            names.append(entry.name)
    return names


def _order(root, names):
    """Alphabetical, except that DEPENDS come first."""
    resolved, visiting, out = set(), set(), []

    def visit(name):
        if name in resolved:
            return
        if name in visiting:
            raise OneFrameworkError(f"Circular module dependency involving {name!r}")
        visiting.add(name)
        depends = _peek_depends(root, name)
        for dep in depends:
            if dep not in names:
                raise OneFrameworkError(
                    f"Module {name!r} depends on {dep!r}, which is not present "
                    f"in {root}."
                )
            visit(dep)
        visiting.discard(name)
        resolved.add(name)
        out.append(name)

    for name in names:
        visit(name)
    return out


def _peek_depends(root, name):
    """Read DEPENDS without importing the module (import order matters)."""
    init = Path(root) / name / "__init__.py"
    try:
        source = init.read_text(encoding="utf-8")
    except OSError:
        return ()
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "DEPENDS":
                    try:
                        return tuple(ast.literal_eval(node.value))
                    except ValueError:
                        return ()
    return ()


def load_all(root, only=None) -> list[Module]:
    """Import every module under *root* and return them in load order."""
    root = Path(root).resolve()
    parent = str(root.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    names = discover(root)
    if only:
        missing = [n for n in only if n not in names]
        if missing:
            raise OneFrameworkError(f"No such module(s) in {root}: {', '.join(missing)}")
        names = [n for n in names if n in only]

    loaded = []
    for name in _order(root, names):
        cached = MODULES.get(name)
        if cached is not None and cached.path.parent == root:
            loaded.append(cached)
            continue

        # A module of the same name loaded from a *different* directory would
        # otherwise be served from sys.modules -- two apps each with a
        # "contacts" module must not share one import.
        _evict(name, root)
        importlib.invalidate_caches()
        try:
            package = importlib.import_module(name)
        except Exception as exc:
            raise OneFrameworkError(f"Module {name!r} failed to import: {exc}") from exc
        module = Module(name, root / name, package)
        MODULES[name] = module
        loaded.append(module)
    return loaded


def _evict(name, root):
    """Drop a cached import of *name* that came from somewhere other than root."""
    existing = sys.modules.get(name)
    if existing is None:
        return
    origin = getattr(existing, "__file__", "") or ""
    if origin.startswith(str(root)):
        return
    for key in [k for k in sys.modules if k == name or k.startswith(f"{name}.")]:
        del sys.modules[key]
