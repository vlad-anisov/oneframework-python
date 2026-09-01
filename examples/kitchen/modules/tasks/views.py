"""The list section: everything a list can do, and a record form with tabs."""

from oneframework import (
    Button, Col, Create, Delete, Filter, Group, List, Row, Search, Sort, Tab, Tabs, View,
    record,
)

from .models import Task


class TaskItem(View):
    model = Task

    def ui(self, record):
        #: drag handle + toggle + title + a custom widget from static/widgets.js,
        #: and a Delete that is also a swipe gesture
        #:
        #: Два ``visible=`` здесь стоят намеренно, и они разные -- это
        #: единственное место в примерах, где условие про запись вообще
        #: написано, а без него **обе дороги строки не исполняются ни разу**:
        #:
        #: * ``~record.done`` -- условие про булево поле с умолчанием, и оно
        #:   становится колонкой ``CASE WHEN`` в том же SELECT
        #:   (``session.py:_condition_column``): весь список отвечает одним
        #:   запросом;
        #: * ``record.assignee.is_null()`` -- условие про связь, у которой
        #:   умолчания нет, а значит она бывает NULL, а NULL -- ни истина, ни
        #:   ложь. Колонкой такое не считается, и остаётся единственная дорога:
        #:   ``evaluate()`` по записи, **на каждую строку и на каждый слот**.
        #:
        #: Вторая дорога -- та самая, которую нельзя мерить на пустом месте:
        #: перенос вычислителя за границу WASM упирается в неё, и пока условия
        #: не написано, замер показывал бы ноль вызовов.
        return Row(
            record.sequence(widget="handle"),
            record.done(widget="toggle"),
            record.title(widget="title"),
            record.state(widget="pill"),
            record.due(widget="text", visible=record.assignee.is_null()),
            Button(icon="delete", action=record.delete(swipe=True), visible=~record.done),
        )


class TaskDetail(View):
    model = Task

    def ui(self, record):
        return Tabs(
            Tab(
                "Главное",
                Group(
                    record.title(),
                    record.state(widget="segmented"),
                    record.priority(),
                    record.due(widget="calendar"),
                    label="Задача",
                ),
                Row(
                    Col(record.progress(widget="range")),
                    Col(record.progress(widget="gauge")),
                ),
                record.done(),
            ),
            Tab(
                "Детали",
                Group(
                    record.estimate(widget="picker"),
                    record.assignee(widget="autocomplete"),
                    record.labels(widget="chips"),
                    label="Планирование",
                ),
                record.notes(widget="rich"),
            ),
            Tab(
                "Опасное",
                Button("Удалить задачу", action=record.delete()),
            ),
        )


class Board(View):
    """The list itself: search, filters, sorts, manual order, paging."""

    def ui(self, record):
        return (
            Button(place="fab", action=Task.create(open=TaskDetail)),
            List(
                Task,
                item=TaskItem,
                open=TaskDetail,
                page_size=20,
                search=Search(
                    record.title,
                    Filter("Открытые", ~record.done, default=True),
                    Filter("Готовые", record.done),
                    Filter("Срочные", record.priority >= 4),
                    Sort("Вручную", record.sequence, default=True),
                    Sort("По сроку", record.due),
                    Sort("Сначала новые", record.created_at.desc()),
                ),
            ),
        )
