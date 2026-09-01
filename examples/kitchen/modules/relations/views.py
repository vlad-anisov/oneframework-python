"""All four relation kinds on one record, each with more than one widget."""

from oneframework import (
    Button, Col, Create, Delete, Group, List, Row, Search, Sort, Tab, Tabs, View,
)

from .models import Contact, Note


class ContactItem(View):
    model = Contact

    def ui(self, record):
        return Row(
            record.name(widget="title"),
            record.company(widget="tag"),
            record.skills(widget="count"),
            Button(icon="delete", action=record.delete(swipe=True)),
        )


class NoteItem(View):
    model = Note

    def ui(self, record):
        return Row(record.text(widget="title"),
                   Button(icon="delete", action=record.delete()))


class NoteEntry(View):
    """First cell is the moment, the rest is the entry -- Timeline's own split."""

    model = Note

    def ui(self, record):
        return Row(
            record.created_at(widget="title"),
            record.text(widget="title"),
            Button(icon="delete", action=record.delete()),
        )


class NoteDetail(View):
    model = Note
    # Заметка открывается из ленты на том же экране, и путь к ней весь
    # состоит из этого экрана. Стоит рядом с ContactDetail, который
    # промолчал: две половины признака видны на одной витрине.
    crumbs = False

    def ui(self, record):
        return (record.text(), record.body(widget="textarea"), record.contact(),
                Button("Удалить", action=record.delete()))


class ContactDetail(View):
    model = Contact

    def ui(self, record):
        return Tabs(
            Tab(
                "Контакт",
                Group(record.name(), record.mail(), record.tel(), label="Кто"),
                Row(
                    Col(record.company(widget="select")),
                    Col(record.company(widget="chips")),
                ),
            ),
            Tab(
                "Связи",
                Group(
                    record.skills(widget="tags"),
                    label="Один-к-одному и многие-ко-многим",
                ),
                record.skills(widget="chips"),
                record.skills(widget="tags"),
                # Единственное на витрине «выбери несколько». Без него ветка
                # правила «лист, а не меню» ничем не рисуется, и проверить её
                # пальцем было бы не на чем.
                record.skills(widget="list"),
                Group(record.notes(widget="count"),
                      label="Заметки (один-ко-многим)"),
            ),
            Tab("Опасное", Button("Удалить контакт", action=record.delete())),
        )


class Contacts(View):

    def ui(self, record):
        return (
            Button(place="fab", action=Contact.create(open=ContactDetail)),
            List(
                Contact,
                item=ContactItem,
                open=ContactDetail,
                search=Search(
                    record.name,
                    Sort("По имени", record.name, default=True),
                ),
            ),
            List(Note, item=NoteEntry, open=NoteDetail, display="timeline"),
        )
