"""Field gallery: every field type the framework offers, in one screen.

This doubles as the acceptance test for the field library -- if a type renders
here, it works end to end.
"""

from oneframework import (
    App, Barcode, Boolean, Button, Color, Create, Date, Delete, Duration, Email, Filter, Float,
    GeoPoint, Html, Image, Integer, List, Many2many, Many2one, Model, Monetary, One2one,
    Password, Percent, Phone, Rating, Row, Search, Selection, Sort, String, Text, Time, Url,
    View,
)


class Category(Model):
    name = String("Category", required=True)
    color = Color("Colour")


class Profile(Model):
    """The target of the One2one below."""

    nickname = String("Nickname", required=True)
    bio = String("Bio")


class Sample(Model):
    # text family
    title = String("Char", required=True)
    notes = Text("Text")
    article = Html("Html")
    secret = Password("Password")
    mail = Email("Email")
    tel = Phone("Phone")
    site = Url("Url")
    sku = Barcode("Barcode")

    # numeric family
    count = Integer("Integer")
    ratio = Float("Float")
    price = Monetary("Monetary", currency="EUR")
    done_pct = Percent("Percent")
    spent = Duration("Duration")
    stars = Rating("Rating", maximum=5)

    # other scalars
    active = Boolean("Boolean")
    state = Selection(
        [("draft", "Draft"), ("review", "In review"), ("done", "Done")], "Selection"
    )
    accent = Color("Color")

    # temporal
    due = Date("Date")
    at = Time("Time")

    # binary
    photo = Image("Image")

    # geo
    place = GeoPoint("GeoPoint")

    # relational
    category = Many2one(Category, "Many2one")
    profile = One2one(Profile, "One2one")
    tags = Many2many(Category, "Many2many")


class SampleItem(View):
    model = Sample

    def ui(self, record):
        return Row(
            record.title(widget="title"),
            record.state(widget="badge"),
            Button(icon="delete", action=record.delete()),
        )


class SampleDetail(View):
    model = Sample

    def ui(self, record):
        return (
            record.title(),
            record.state(),
            record.stars(),
            record.price(),
            record.done_pct(widget="progress"),
            record.count(widget="stepper"),
            record.ratio(),
            record.active(),
            record.mail(),
            record.tel(),
            record.site(),
            record.secret(),
            record.due(),
            record.at(),
            record.accent(),
            record.photo(),
            record.category(),
            record.profile(),
            record.notes(widget="textarea"),
            Button("Delete", action=record.delete()),
        )


class Gallery(View):
    def ui(self, record):
        return (
            Button(place="fab", action=Sample.create(open=SampleDetail)),
            List(
                Sample,
                item=SampleItem,
                open=SampleDetail,
                search=Search(
                    record.title,
                    Filter("Active", record.active),
                    Sort("Newest", record.created_at.desc(), default=True),
                ),
            ),
        )


app = App(Gallery, title="Gallery", color="#00629E")
