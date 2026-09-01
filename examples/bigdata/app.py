"""Stress app: enough records that paging, infinite scroll and virtual list
all actually engage."""

from oneframework import (
    App, Boolean, Button, Create, Delete, Filter, Integer, List, Model, Row, Search, Sort,
    String, View,
)


class Entry(Model):
    label = String("Label", required=True)
    done = Boolean("Done")
    weight = Integer("Weight")
    position = Integer()


class EntryItem(View):
    model = Entry

    def ui(self, record):
        return Row(
            record.position(widget="handle"),
            record.done(widget="toggle"),
            record.label(widget="title"),
            Button(icon="delete", action=record.delete(swipe=True)),
        )


class EntryDetail(View):
    model = Entry

    def ui(self, record):
        return (
            record.label(),
            record.weight(widget="stepper"),
            record.done(),
            Button("Delete", action=record.delete()),
        )


class Big(View):
    def ui(self, record):
        return (
            Button(place="fab", action=Entry.create(open=EntryDetail)),
            List(
                Entry,
                item=EntryItem,
                open=EntryDetail,
                page_size=100,
                search=Search(
                    record.label,
                    Filter("Open", ~record.done, default=True),
                    Sort("Manual", record.position, default=True),
                    Sort("Newest", record.created_at.desc()),
                ),
            ),
        )


app = App(Big, title="Bigdata", color="#8E4585")
