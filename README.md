# oneframework-python

Объявление приложения на Python. Работает поверх
[ядра](https://github.com/vlad-anisov/oneframework).

```bash
git clone https://github.com/vlad-anisov/oneframework-python.git
pip install ./oneframework-python
```

> В PyPI пакет ещё не выложен. Что он ставится и работает **из установки**, а
> не только из дерева, проверяется — `tests/test_installed.py`.

```python
from oneframework import (
    App, Boolean, Button, Filter, Integer, List, Many2one, Model, Row,
    Search, Sort, String, Text, View, expr, view,
)


class Tag(Model):
    name = String("Название", required=True)


class TodoLine(Model):
    text = String("Задача", required=True)
    description = Text("Описание")
    tag = Many2one(Tag, "Тег")
    completed = Boolean("Выполнено")
    sequence = Integer()


class TodoLineItem(View):
    model = TodoLine

    def ui(self, record):
        return Row(
            record.sequence(widget="handle"),
            record.completed(widget="toggle"),
            record.text(widget="title"),
            record.tag(widget="tag"),
            Button(icon="delete", action=record.delete()),
        )


class TodoLineDetail(View):
    model = TodoLine

    def ui(self, record):
        return (record.text(), record.description(widget="textarea"),
                record.tag(), record.completed())


class Todo(View):
    tag = Many2one(Tag, "Тег")

    def ui(self, record):
        return (
            view.tag(widget="chips"),
            List(
                TodoLine,
                item=TodoLineItem,
                open=TodoLineDetail,
                domain=expr("record.tag = view.tag"),
                search=Search(
                    record.text,
                    Filter("Осталось", expr("!record.completed"), default=True),
                    Sort("По порядку", record.sequence, default=True),
                ),
            ),
        )


app = App(Todo, theme="ios")
```

Это всё приложение. Полный вариант —
[`todo`](https://github.com/vlad-anisov/oneframework-examples/tree/main/todo).

## Что делает эта библиотека

Ровно одно: печатает **пакет объявления** — JSON по договору
[`protocol/declaration.json`](https://github.com/vlad-anisov/oneframework/blob/main/protocol/declaration.json).
Всё остальное — база, экраны, обмен, сборка, PWA, APK — делает ядро, одинаково
для всех трёх языков.

Единственная дверь отсюда наружу:

```bash
python3 -m oneframework declare app.py
```

Зовёт её ядро само, когда вы даёте ему файл `.py`.

## Собирает ядро

Своей команды у привязки нет намеренно: `oneframework` одна на все языки и
живёт в ядре.

```bash
git clone https://github.com/vlad-anisov/oneframework.git
cd oneframework && npm install
npx oneframework dev ../app.py
npx oneframework build android ../app.py
```

Что умеет команда, как поднять точку обмена и что нужно для Android —
[в записке ядра](https://github.com/vlad-anisov/oneframework#readme).

## Возле приложения

`seed.py` рядом с `app.py`, отдающий `seed(db)`, наполняет базу показательными
данными при первом запуске на пустой базе.

Приложение из нескольких разделов — это список назначений, у каждого свой
корневой вид:

```python
app = App(
    Screen(Tasks, label="Задачи", icon="check"),
    Screen(Contacts, label="Связи", icon="group"),
    title="Work",
)
```

Как их **показать** — не дело объявления. Уже 768 пикселей — нижняя полоса
вкладок, шире — постоянная боковая панель. У каждого назначения своя стопка
переходов, и переключение раздела оставляет её там, где вы её бросили.

Раздел может принести модуль, и «установить модуль» значит ровно это:

```python
# modules/tasks/__init__.py
SCREEN = Screen(Board, label="Задачи", icon="check")
```

### Список: строками, таблицей или записью рядом

```python
List(Product, item=ProductItem, open=ProductDetail, display="table",
     columns=(name(widget="title"), sku(), price(), stock(widget="stepper")))
```

* `display="auto"` (по умолчанию) — строками; в широком окне открытая запись
  рисуется **рядом** со списком, а не поверх;
* `display="table"` — таблица там, где колонки помещаются, и те же строки там,
  где не помещаются. Таблице нужна вся ширина, и этот экран от деления
  отказывается;
* `display="list"` — строками всегда;
* `display="timeline"` — по времени.

Без `columns=` колонками таблицы становятся ячейки вида строки: список описан
один раз. `columns=` нужен, когда строка на телефоне должна быть короче
таблицы.

### Что приносит модуль

```
modules/tasks/
  __init__.py        DEPENDS + SCREEN
  models.py  views.py
  seed.py            показательные данные, один раз на модуль
  static/widgets.js  свой виджет
  static/widgets.css
```

## Проверки

```bash
python3 -m pytest -q
```

Часть спит с названной причиной: проверка про привязку, но обстановку ей даёт
ядро, а ядра рядом нет. Решает это `нужно_ядро` в `tests/conftest.py`.
Проверка, которая не может пройти там, куда её положили, не сторож: она
приучает смотреть на красное и не читать.

## Лицензия

MIT.
