# oneframework

Write a local-first application in declarative Python; get a Web app, an
installable offline PWA and an Android APK — without writing any JavaScript,
HTML, CSS or SQL.

```python
from oneframework import (
    App, Boolean, Button, Color, Delete, Filter, Integer, List, Many2one, Model,
    Row, Search, Sort, String, Text, View, record, view,
)


class Tag(Model):
    name = String("Название", required=True)
    color = Color("Цвет")


class TodoLine(Model):
    text = String("Задача", required=True)
    description = Text("Описание")
    tag = Many2one(Tag, "Тег")
    completed = Boolean("Выполнено")
    sequence = Integer()


class TodoLineItem(View):
    model = TodoLine

    def ui(self):
        return Row(
            record.sequence(widget="handle"),
            record.completed(widget="toggle"),
            record.text(widget="title"),
            record.tag(widget="tag"),
            Button(icon="delete", action=Delete()),
        )


class Todo(View):
    tag = Many2one(Tag, "Тег")

    def ui(self):
        return (
            view.tag(widget="chips"),
            List(
                TodoLine,
                item=TodoLineItem,
                open=TodoLineDetail,
                domain=record.tag == view.tag,
                search=Search(
                    record.text,
                    Filter("Осталось", ~record.completed, default=True),
                    Sort("По порядку", record.sequence, default=True),
                    Sort("Сначала новые", record.created_at.desc()),
                ),
            ),
        )


app = App(Todo, theme="ios")
```

That is the whole application. The complete version lives in
[`examples/todo/app.py`](examples/todo/app.py).

---

## 1. Install

This repository is the **Python binding**: it prints the declaration bundle.
Everything else — the database, the screens, the sync, the build — is done by
the [core](https://github.com/vlad-anisov/oneframework), the same for every
language.

Requirements: **Python ≥ 3.10**, **Node ≥ 20**. For Android additionally
**JDK 21+** and the **Android SDK** (platform 35 + build-tools).

```bash
git clone https://github.com/vlad-anisov/oneframework.git ../oneframework
cd ../oneframework && npm install && cd -
python3 -m pip install -e .
export ONEFRAMEWORK_CORE="$(cd ../oneframework && pwd)"
```

`pip install -e .` puts the `oneframework` command on your PATH.

The binding looks for the core in three places, in this order:
`ONEFRAMEWORK_CORE`, the `oneframework` package in `node_modules`, a sibling
directory in a development tree. A named-but-wrong path is refused out loud — a
typo there would silently build your app with a different core.

## 2. Web development

```bash
oneframework dev examples/todo/app.py
```

Then open <http://localhost:5173>. Give it a few seconds on first load — the
page appears immediately, then the Python runtime boots behind the progress bar.

Use a narrow window or the browser's device toolbar (⌘⇧M / Ctrl+Shift+M) to see
the mobile layout; the UI is the same one that ships in the APK. Light/dark
follows your OS.

The look is set by `App(theme=...)`. The demo pins `theme="ios"`, so it renders
the iOS idiom everywhere — including in the Android APK. Use `theme="auto"` to
pick per device (Material 3 on Android and desktop, iOS on iPhone/iPad), or
`theme="md"` to pin Material. The seed colour comes from
`App(Todo, color="#386A20")`.

Hot reload applies to the renderer (JS/CSS). Editing `app.py` needs a restart,
because the Python bundle is rebuilt when the server starts.

Validate the DSL without building anything:

```bash
oneframework check examples/todo/app.py
```

### Debugging: `oneframework inspect`

A screen is a pure function of the *definitions* (model schemas, view
documents) and the data. So when a screen is wrong there is always one first
question — is the document wrong, or is the document right and the JavaScript
runtime wrong? The first is Python and is answered here; the second is
DevTools. `oneframework inspect` answers the first without a browser:

```bash
oneframework inspect examples/todo/app.py                  # overview: models, defs, fingerprints
oneframework inspect examples/todo/app.py --tree           # the screen as a node tree
oneframework inspect examples/todo/app.py --view Todo      # the view document that goes into the base
oneframework inspect examples/todo/app.py --model TodoLine # the model schema
oneframework inspect examples/todo/app.py --where Todo.l1  # which view declares that node
oneframework inspect examples/todo/app.py --db dev.db \
    --event '{"type":"set_filter","list_id":"Todo.l1","index":1}'   # and the diff it caused
```

`--db FILE` builds the database once and then reuses it, so record keys stay
put between runs and an event can name a record; the file itself is never
written to — the command works on a copy. `--export CASE.json` writes
definitions + data + expected trees in exactly the shape
`tests/parity/session_driver.mjs` reads, so a bug found in Python goes to the
JavaScript runtime as a replayable file.

The database is a plain SQLite file. For tables, arbitrary queries and
browsing use `sqlite3` or [Datasette](https://datasette.io/); `inspect` does
not duplicate them.

## 3. Tests

Python unit tests (models, DSL, expressions, UNSET, queries, runtime):

```bash
python3 -m pytest tests -q
```

Browser end-to-end tests (they run against the production build, so each suite
needs its own app built first — a suite skips itself when `dist/` holds a
different one):

```bash
oneframework build web examples/todo/app.py && npx playwright test todo
```

```bash
oneframework build web examples/kitchen/app.py && npx playwright test kitchen
```

First run only: `npx playwright install chromium`.

Environment smoke check (Pyodide + sqlite3 from local assets, no CDN):

```bash
node spikes/spike_pyodide.mjs
```

## 4. Production web build

```bash
oneframework build web examples/todo/app.py
```

Output goes to `dist/`. Preview it with:

```bash
npx vite preview --port 4173
```

## 5. PWA / offline

The build emits a manifest, icons and a service worker that precaches the whole
runtime (~15 MB, mostly the Pyodide WASM). To verify offline operation by hand:

1. `npx vite preview --port 4173` and open <http://localhost:4173>
2. wait for the list to appear (the service worker precaches in the background)
3. in DevTools → Network, switch to **Offline**
4. reload — the app boots and all data is still there

The automated version of this is test 27 in `tests/e2e/todo.spec.js`.

## 5a. Two devices: the exchange server

One command serves both halves — the exchange point and the built web client —
so a domain behaves like an ordinary application:

```bash
oneframework serve examples/gtasks/app.py --host 127.0.0.1 --port 8790
```

It builds `dist/` if there is none, keeps the shared database under
`--data` (`.oneframework-server/` by default), answers `POST /sync`, and serves
everything else out of `dist/` — and nothing outside it.

**Where the client calls.** A web client served by this server needs no
configuration at all: it calls `./sync` next to the page it came from. A build
that ships elsewhere — an APK, whose origin belongs to the WebView — has to be
told:

```bash
PYAPP_SYNC_URL=https://example.org oneframework build android examples/gtasks/app.py
```

The same thing can live in the app itself, `App(..., sync="https://example.org")`,
and `PYAPP_SYNC_URL=off` (or `App(sync=False)`) turns the exchange off.

Every screen carries the state in the bar: a cloud when everything is sent, an
arrow with a count when something is not, a crossed-out cloud with no network.
Tapping it says when the last round was and offers one now.

**There is no authentication.** Anyone who knows the address can write. The
server says so in the root response (`X-Pyapp-Stand`, an injected
`window.__PYAPP_STAND__`) and the client repeats it in that same card. Scopes
and accounts are the next piece of work — the place they go is marked in
`SyncServer._since`.

## 6. Android prerequisites

```bash
brew install openjdk@21          # or any JDK >= 21
```

Install the Android SDK (Android Studio, or command-line tools) and make sure
`ANDROID_HOME` points at it — `oneframework` also falls back to
`~/Library/Android/sdk` and `~/Android/Sdk`. A suitable JDK is discovered
automatically; set `JAVA_HOME` to override.

## 7. Android build

```bash
oneframework build android examples/todo/app.py
```

One command runs the whole pipeline: production web build → Capacitor project
creation (first run only) → `cap sync` → `gradlew assembleDebug`, and prints the
resulting artifact.

Add `--install` to also `adb install` and launch it on a running
device/emulator.

## 8. APK path

```
android/app/build/outputs/apk/debug/app-debug.apk
```

## 9. Android emulator

```bash
$ANDROID_HOME/emulator/emulator -list-avds
$ANDROID_HOME/emulator/emulator -avd <name> -no-snapshot -no-audio &
oneframework build android examples/todo/app.py --install
```

The app runs entirely offline once installed — nothing is fetched at runtime.

## 10. Framework structure

```
oneframework/
  errors.py            developer-facing errors with "did you mean" suggestions
  model/
    fields.py          String Boolean Integer Many2one Color Datetime ...
    meta.py            Model metaclass, auto id/created_at/updated_at
    expr.py            expression AST, record/view proxies, UNSET
    query.py           domain -> parameterised SQL
    storage.py         SQLite gateway + storage adapter boundary
  ui/
    view.py            View metaclass, and building a `ui` method's tree
    nodes.py           Component IR (view row col group tabs field list ...)
    screen.py          Screen: one top-level destination of the app
    components.py      public names: Row Col Group Tabs List Button Search ...
  runtime/
    state.py           signals / effects (dependency-tracked reactivity)
    session.py         frames, per-destination stacks, queries, events
    app.py             App entry point
  modules.py           folder-based modules: discovery, DEPENDS, seeds
  bridge/web.py        JSON-only Python <-> JavaScript boundary
  cli/
    main.py            oneframework dev | build | check | inspect
    inspect.py         documents, screen tree, event diffs, replayable cases
    assets.py          Pyodide copy, bundle zip, PWA manifest/icons
    builders/          web.py, android.py  (add ios.py here later)

web/
  src/main.js          app shell, Framework7 init, boot flow
  src/pyodide-host.js  interpreter boot, IDBFS persistence, bundle install
  src/renderer.js      generic Component-IR renderer (views, tabs, panel,
                       master detail, data table, virtual list)
  src/widgets.js       widget registry keyed by (field type, widget)
  src/styles.css       Material-flavoured layer over Framework7
  public/sw.js         offline service worker

examples/
  todo/                the acceptance sample (app.py + seed.py)
  kitchen/             the sink: five module-provided sections, every field
                       type and widget, a data table, master detail
  showcase/            ColorPicker, Stepper, Range, rich text, Calendar,
                       Autocomplete, swipe-to-delete
  bigdata/             500 records: paging, infinite scroll, virtual list
  gallery/             every one of the 29 field types on one screen
  modular/             two modules, dependencies, and a custom JS widget
tests/                 pytest suite + tests/e2e Playwright suite
```

## 11. Several sections in one app

An app is a list of destinations. Each one is a root `View` with a label and an
icon:

```python
app = App(
    Screen(Tasks, label="Задачи", icon="check"),
    Screen(Contacts, label="Связи", icon="group"),
    title="Work",
)
```

How they are *shown* is not part of the DSL. Below 768 px they are a bottom tab
bar; above it a permanent side panel — the two presentations Material 3 and
iPadOS describe for the same structure. Each destination keeps its own
navigation stack, so switching sections leaves every one where you left it.

A module can contribute a section instead, which is all "installing" means:

```python
# modules/tasks/__init__.py
SCREEN = Screen(Board, label="Задачи", icon="check")
```

### Lists: rows, a table, or a record beside the list

```python
List(Product, item=ProductItem, open=ProductDetail, display="table",
     columns=(name(widget="title"), sku(), price(), stock(widget="stepper")))
```

* `display="auto"` (default) — rows; on a wide window an opened record renders
  *beside* the list rather than over it (Framework7 master detail).
* `display="table"` — a Framework7 data table wherever the columns fit, the
  same rows where they do not. A table wants the full width, so this screen
  opts out of the split.
* `display="list"` — rows, always.

Without `columns=` the table's columns *are* the item view's cells, so a list
is described once. Pass `columns=` when a phone row should stay shorter than
the table.

### What a module may ship

```
modules/tasks/
  __init__.py        DEPENDS + SCREEN
  models.py  views.py
  seed.py            demo data, run once per module
  static/widgets.js  oneframework.registerWidget("selection:pill", {...})
  static/widgets.css styles for that widget
```

Try all of it:

```bash
oneframework dev examples/kitchen/app.py
```

## 12. Writing a second application

Create a directory with an `app.py`:

```python
from oneframework import (
    App, Boolean, Button, Delete, Filter, List, Model, Row, Search, Sort,
    String, Text, View, record,
)


class Note(Model):
    title = String("Title", required=True)
    body = Text("Body")
    pinned = Boolean("Pinned")


class NoteItem(View):
    model = Note

    def ui(self):
        return Row(record.pinned(widget="toggle"), record.title(widget="title"),
                   Button(icon="delete", action=Delete()))


class NoteDetail(View):
    model = Note

    def ui(self):
        return (record.title(), record.body(widget="textarea"), record.pinned(),
                Button("Delete", action=Delete()))


class Notes(View):
    def ui(self):
        return (
            List(Note, item=NoteItem, open=NoteDetail,
                 search=Search(record.title,
                               Filter("Pinned", record.pinned),
                               Sort("Newest", record.created_at.desc(),
                                    default=True))),
        )


app = App(Notes)
```

Then:

```bash
oneframework dev path/to/app.py
oneframework build android path/to/app.py
```

Optional: put a `seed.py` next to `app.py` exporting `seed(db)` to load demo
data the first time the app starts against an empty database.

## 13. Documentation

[`docs/architecture.md`](docs/architecture.md) explains the design, in
particular how a `ui` method's tree is built on every render and how
`record.<field>` finds the model it belongs to.

## License

MIT.
