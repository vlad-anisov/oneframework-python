"""Приложение на одно правило: какие условия строки уходят в запрос.

Существует ради сверки двух рантаймов, а не ради показа. В gtasks и kitchen
условия строки говорят почти только о булевых колонках -- то есть о тех, что
есть у записи всегда, -- и потому уезжают в SQL. Здесь рядом стоят все исходы
правила, каждый своим списком, и питон с джаваскриптом обязаны выбрать для
каждого один и тот же путь: выбери они разные, ячейки разошлись бы на пустом
значении и молча.

Списков три, а не один, намеренно: одно негодное гнездо уводит на построчный
путь **весь** список, поэтому в общем списке годные условия так и не
проверились бы. Исходы такие:

* колонки, которые есть у записи всегда, -- запрос;
* пустая колонка **под ``is_null()``** -- тоже запрос: ``IS NULL`` отвечает 0
  или 1 при любом содержимом, и ровно это же считает ``evaluate``;
* пустая колонка **в сравнении** -- построчно: SQL ответил бы неизвестностью,
  колонка превратила бы её в ложь, а ``evaluate`` на том же месте отвечает
  истиной.
"""

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
    """Условия только о колонках, которые есть у записи всегда."""

    model = Memo

    def ui(self, record):
        return Row(
            record.title(widget="title", visible=~record.done),
            record.rank(visible=record.rank > 1),
            record.done(widget="checkbox", visible=(record.rank > 0) & ~record.done),
            Button(icon="delete", action=record.delete(), visible=record.done),
        )


class NullableRow(View):
    """Пустая колонка под ``is_null()``: неизвестности не возникает.

    Три формы, которые правило обязано пропустить в SQL: сама проверка,
    отрицание над ней и ``|`` с безопасной колонкой рядом.
    """

    model = Memo

    def ui(self, record):
        return Row(
            record.title(widget="title", visible=record.due.is_null()),
            record.due(visible=~record.due.is_null()),
            record.rank(visible=record.due.is_null() | record.done),
        )


class CompareRow(View):
    """Пустая колонка в сравнении: NULL -- ни истина, ни ложь.

    ``due != <дата>`` у записи без срока даёт в SQL NULL, ``CASE WHEN`` делает
    из него ложь, а ``evaluate`` на том же месте отвечает истиной. Пока эти двое
    расходятся, такое условие в запрос не уходит.
    """

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
