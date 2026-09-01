"""Every field type, and every widget each of them offers, on tappable tabs.

The point of this screen is that a field renders differently only because the
DSL asked for a different `widget=` -- the model, the storage and the runtime
are the same for all of them.
"""

from oneframework import (
    Accordion, Button, Col, Create, Delete, Group, List, Row, Search, Section, Sort, Tab, Tabs,
    View,
)

from .models import Sample


class SampleItem(View):
    model = Sample

    def ui(self, record):
        return Row(
            #: Boolean без widget= в строке -- это маленький флажок Framework7,
            #: единственный вид, которого на этом экране до сих пор не было:
            #: в форме тот же самый Boolean занимает строку целиком.
            record.active(),
            record.title(widget="title"),
            record.state(widget="badge"),
            record.stars(widget="stepper"),
            Button(icon="delete", action=record.delete(swipe=True)),
        )


class SampleDetail(View):
    model = Sample

    def ui(self, record):
        return Tabs(
            Tab(
                "Текст",
                Group(
                    record.title(),
                    record.title(widget="title"),
                    record.mail(), record.tel(), record.site(),
                    record.secret(), record.sku(),
                    label="Char и его родня",
                ),
                Section("Text"),
                record.notes(widget="textarea"),
                record.notes(widget="rich"),
                Section("Html"),
                record.article(widget="rich"),
                record.article(widget="textarea"),
            ),
            Tab(
                "Числа",
                Group(
                    record.count(),
                    record.count(widget="stepper"),
                    record.count(widget="range"),
                    label="Integer",
                ),
                Group(
                    record.ratio(),
                    record.price(),
                    record.price(widget="number"),
                    label="Float и Monetary",
                ),
                Section("Percent"),
                Row(
                    Col(record.done_pct(widget="range")),
                    Col(record.done_pct(widget="gauge")),
                ),
                record.done_pct(widget="progress"),
                record.done_pct(widget="unit"),
                Section("Duration и Rating"),
                record.spent(widget="picker"),
                record.spent(widget="stepper"),
                record.stars(),
                record.stars(widget="stepper"),
            ),
            Tab(
                "Выбор",
                Group(
                    record.active(),
                    record.active(widget="toggle"),
                    label="Boolean",
                ),
                Section("Selection"),
                record.state(widget="select"),
                record.state(widget="segmented"),
                record.state(widget="chips"),
                record.state(widget="radio"),
                record.state(widget="picker"),      # F7 Picker
                record.state(widget="pill"),        # from a module
                Section("Color"),
                Row(
                    Col(record.accent()),
                    Col(record.accent()),
                ),
            ),
            Tab(
                "Время",
                Group(
                    record.due(),
                    record.due(widget="text"),
                    record.at(),
                    record.at(widget="picker",      # F7 Picker
                              help="Колесо в шите — компонент Picker"),
                    record.stamp(),
                    label="Date, Time, Datetime",
                ),
                Accordion(
                    record.due(),
                    record.at(),
                    label="Сворачиваемый блок (Accordion)",
                ),
            ),
            Tab(
                "Файлы",
                Section("Image"),
                record.photo(),
                record.photo(widget="browser",      # F7 PhotoBrowser
                             help="Тапни, чтобы открыть на весь экран"),
                Section("Binary и Signature"),
                record.attachment(),
                record.sign(),
                Section("GeoPoint"),
                record.place(),
                Button("Удалить образец", action=record.delete()),
            ),
        )


class Widgets(View):

    def ui(self, record):
        return (
            Button(place="fab", action=Sample.create(open=SampleDetail)),
            List(
                Sample,
                item=SampleItem,
                open=SampleDetail,
                search=Search(
                    record.title,
                    Sort("Сначала новые", record.created_at.desc(), default=True),
                ),
            ),
        )
