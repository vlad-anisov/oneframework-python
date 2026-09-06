"""Приложение на одно правило: какие условия строки уходят в запрос."""

from oneframework import (
    App, Boolean, Button, Date, Delete, Filter, Integer, List, Model, Row,
    Screen, Search, Sort, String, View,
)

class Memo(Model):
    title = String("Заголовок", required=True)
    done = Boolean("Выполнено")
    rank = Integer("Ранг")
    due = Date("Срок")

class SolidRow(View):
    model = Memo

    def ui(self, record):
        return Row(
            record.title(widget="title", visible=~record.done),
            record.rank(visible=record.rank > 1),
            record.done(widget="checkbox", visible=(record.rank > 0) & ~record.done),
            Button(icon="delete", action=record.delete(), visible=record.done),
        )

class NullableRow(View):
    """Пустая колонка под ``is_null()``: неизвестности не возникает."""
    model = Memo

    def ui(self, record):
        return Row(
            record.title(widget="title", visible=record.due.is_null()),
            record.due(visible=~record.due.is_null()),
            record.rank(visible=record.due.is_null() | record.done),
        )

class CompareRow(View):
    model = Memo

    def ui(self, record):
        return Row(
            record.title(widget="title", visible=record.due != "2026-02-01"),
            record.rank(visible=~record.done),
        )

class Wall(View):
    def ui(self, record):
        return (
            List(Memo, item=SolidRow,
                 search=Search(record.title,
                               Filter("Открытые", ~record.done),
                               Sort("По рангу", record.rank, default=True))),
            List(Memo, item=NullableRow, order=record.title),
            List(Memo, item=CompareRow, order=record.rank),
        )

app = App(Screen(Wall), title="Row rule")
