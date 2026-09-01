"""One model carrying every field type the framework offers."""

from oneframework import (
    Barcode,
    Binary,
    Boolean,
    Color,
    Date,
    Datetime,
    Duration,
    Email,
    Float,
    GeoPoint,
    Html,
    Image,
    Integer,
    Model,
    Monetary,
    Password,
    Percent,
    Phone,
    Rating,
    Selection,
    String,
    Text,
    Time,
    Url,
)


class Sample(Model):
    # text
    title = String("Char", required=True)
    notes = Text("Text")
    article = Html("Html")
    secret = Password("Password")
    mail = Email("Email")
    tel = Phone("Phone")
    site = Url("Url")
    sku = Barcode("Barcode")

    # numeric
    count = Integer("Integer")
    ratio = Float("Float")
    price = Monetary("Monetary", currency="€")
    done_pct = Percent("Percent")
    spent = Duration("Duration")
    stars = Rating("Rating", maximum=5)

    # other scalars
    active = Boolean("Boolean")
    state = Selection(
        [("draft", "Черновик"), ("review", "На проверке"), ("done", "Готово")],
        "Selection",
        default="draft",
    )
    accent = Color("Color")

    # temporal
    due = Date("Date")
    at = Time("Time")
    stamp = Datetime("Datetime")

    # binary
    photo = Image("Image")
    attachment = Binary("Binary")
    sign = Image("Signature")

    # geo
    place = GeoPoint("GeoPoint")
