from oneframework import (
    Button, Create, Delete, Group, List, Row, Search, Section, Sort, Tab, Tabs, View,
)

from .models import Person


class PersonItem(View):
    model = Person

    def ui(self, record):
        return Row(
            record.name(widget="title"),
            record.company(widget="tag"),
            Button(icon="delete", action=record.delete(swipe=True)),
        )


class PersonDetail(View):
    model = Person

    def ui(self, record):
        return (
            Section("Contact"),
            Group(
                record.name(),
                record.mail(),
                record.tel(),
                label="Reach",
            ),
            Tabs(
                Tab("Details", record.company(), record.passport(),
                    record.about(widget="textarea")),
                Tab("Photo", record.photo()),
            ),
            Button("Delete", action=record.delete()),
        )


class ContactsBoard(View):
    def ui(self, record):
        return (
            Button(place="fab", action=Person.create(open=PersonDetail)),
            List(
                Person,
                item=PersonItem,
                open=PersonDetail,
                search=Search(
                    record.name,
                    Sort("A→Z", record.name, default=True),
                    Sort("Newest", record.created_at.desc()),
                ),
            ),
        )
