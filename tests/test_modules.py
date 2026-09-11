"""Folder-based modules: discovery, ordering, roots and seeds."""

import textwrap

import pytest


from oneframework import String, discover, load_all
from oneframework.errors import OneFrameworkError
from oneframework.modules import MODULES
from oneframework.ui.view import View

def write_module(root, name, body="", depends=None, extra=None):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    header = f"DEPENDS = {tuple(depends)!r}\n" if depends else ""
    (folder / "__init__.py").write_text(header + textwrap.dedent(body))
    for filename, content in (extra or {}).items():
        (folder / filename).parent.mkdir(parents=True, exist_ok=True)
        (folder / filename).write_text(textwrap.dedent(content))
    return folder

@pytest.fixture(autouse=True)
def clean_registry():
    MODULES.clear()
    yield
    MODULES.clear()

def test_a_folder_with_init_is_a_module(tmp_path):
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    (tmp_path / "notes").mkdir()                 # no __init__.py
    (tmp_path / "_private").mkdir()
    (tmp_path / "_private" / "__init__.py").touch()

    assert discover(tmp_path) == ["alpha", "beta"]

def test_missing_directory_is_a_clear_error(tmp_path):
    with pytest.raises(OneFrameworkError) as excinfo:
        discover(tmp_path / "nope")
    assert "not found" in str(excinfo.value)

def test_modules_load_alphabetically(tmp_path):
    for name in ("gamma", "alpha", "beta"):
        write_module(tmp_path, name)
    assert [m.name for m in load_all(tmp_path)] == ["alpha", "beta", "gamma"]

def test_depends_are_loaded_first(tmp_path):
    write_module(tmp_path, "zeta")
    write_module(tmp_path, "alpha", depends=["zeta"])
    order = [m.name for m in load_all(tmp_path)]
    assert order.index("zeta") < order.index("alpha")

def test_missing_dependency_names_both_sides(tmp_path):
    write_module(tmp_path, "alpha", depends=["ghost"])
    with pytest.raises(OneFrameworkError) as excinfo:
        load_all(tmp_path)
    message = str(excinfo.value)
    assert "alpha" in message and "ghost" in message

def test_circular_dependency_is_detected(tmp_path):
    write_module(tmp_path, "alpha", depends=["beta"])
    write_module(tmp_path, "beta", depends=["alpha"])
    with pytest.raises(OneFrameworkError) as excinfo:
        load_all(tmp_path)
    assert "Circular" in str(excinfo.value)

def test_only_loads_a_subset(tmp_path):
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    assert [m.name for m in load_all(tmp_path, only=["beta"])] == ["beta"]

def test_a_broken_module_names_itself(tmp_path):
    write_module(tmp_path, "alpha", body="raise ValueError('boom')")
    with pytest.raises(OneFrameworkError) as excinfo:
        load_all(tmp_path)
    assert "alpha" in str(excinfo.value) and "boom" in str(excinfo.value)

def test_module_exposes_its_seed_and_static_files(tmp_path):
    write_module(
        tmp_path, "alpha",
        extra={
            "seed.py": "def seed(db):\n    db.seeded = True\n",
            "static/widget.js": "// custom widget\n",
        },
    )
    module = load_all(tmp_path)[0]
    assert callable(module.seed)
    assert [p.name for p in module.static_files()] == ["widget.js"]

def test_module_without_seed_reports_none(tmp_path):
    write_module(tmp_path, "alpha")
    assert load_all(tmp_path)[0].seed is None

# ------------------------------------------------------------------- App
def test_app_takes_its_root_from_a_module(tmp_path):
    write_module(
        tmp_path, "alpha",
        body='''
        from oneframework import View, Model, Row, String

        class Thing(Model):
            name = String("Name")

        class Home(View):
            def ui(self, record):
                return ()

        ROOT = Home
        ''',
    )
    from oneframework import App

    app = App(modules=load_all(tmp_path), title="Modular")
    assert app.root_view.__name__ == "Home"
    assert [m.name for m in app.modules] == ["alpha"]

def test_app_requires_at_least_one_screen(tmp_path):
    from oneframework import App
    from oneframework.errors import DslError

    write_module(tmp_path, "alpha",
                 body="from oneframework import View\n\n\nclass A(View):\n"
                      "    def ui(self, record):\n        return ()\n")
    with pytest.raises(DslError) as excinfo:
        App(modules=load_all(tmp_path))
    assert "SCREEN" in str(excinfo.value)

def test_each_module_contributes_a_screen(tmp_path):
    from oneframework import App

    for name in ("alpha", "beta"):
        write_module(
            tmp_path, name,
            body=f"from oneframework import View\n\n\nclass V{name}(View):\n"
                 f"    def ui(self, record):\n        return ()\n\n\nROOT = V{name}\n",
        )
    app = App(modules=load_all(tmp_path))
    assert [s.key for s in app.screens] == ["Valpha", "Vbeta"]
    assert [s.label for s in app.screens] == ["Alpha", "Beta"]

def test_module_screen_declares_label_and_icon(tmp_path):
    from oneframework import App

    write_module(
        tmp_path, "alpha",
        body='''
        from oneframework import Screen, View

        class Home(View):
            def ui(self, record):
                return ()

        SCREEN = Screen(Home, label="Главная", icon="house")
        ''',
    )
    app = App(modules=load_all(tmp_path))
    assert app.meta()["screens"] == [
        {"key": "Home", "label": "Главная", "icon": "house", "view": "Home",
         "master_detail": True}
    ]

def _пакетом(app, seed=None):
    """Приложение -> пакет объявления: дорога в план теперь одна."""
    from oneframework.declaration import Bundle, declare

    return Bundle(declare(app, seed))

class _Дом(View):
    def ui(self, record):
        return ()
