"""A list that asks to be a table: the same rows, the same fields, one word."""

from oneframework import (
    Button, Create, Delete, Filter, Group, List, Row, Search, Sort, View,
)

from .models import Product


class ProductItem(View):
    model = Product

    def ui(self, record):
        #: a phone row shows what fits on a phone
        return Row(
            record.name(widget="title"),
            record.kind(widget="badge"),
            record.rating(),
            Button(icon="delete", action=record.delete()),
        )


class ProductDetail(View):
    model = Product

    def ui(self, record):
        return (
            Group(record.name(), record.sku(), record.kind(widget="radio"),
                  label="Что это"),
            # two columns once the window is wide enough -- Framework7's own grid
            Group(record.price(), record.stock(widget="stepper"),
                  record.rating(), record.active(), label="Продажа", cols=2),
            Button("Удалить", action=record.delete()),
        )


class Catalog(View):
    """A phone sees rows; a window wide enough sees the whole record."""

    def ui(self, record):
        return (
            Button(place="fab", action=Product.create(open=ProductDetail)),
            List(
                Product,
                item=ProductItem,
                open=ProductDetail,
                display="table",
                # ...and the table, where there is room, shows the whole record
                columns=(
                    record.name(widget="title"),
                    record.sku(),
                    record.kind(widget="badge"),
                    record.price(),
                    record.stock(widget="stepper"),
                    record.rating(),
                    record.active(widget="toggle"),
                    Button(icon="delete", action=record.delete()),
                ),
                search=Search(
                    record.name,
                    Filter("В продаже", record.active, default=True),
                    Filter("Заканчивается", record.stock < 10),
                    Sort("По названию", record.name, default=True),
                    Sort("Дороже сначала", record.price.desc()),
                    Sort("Остаток", record.stock),
                ),
            ),
        )
