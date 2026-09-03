"""oneframework -- write a local-first Web/PWA/Android app in declarative Python.

    from oneframework import *

    class Tag(Model):
        name = String("Name", required=True)
        color = Color("Color")

    class Todo(View):
        ui = (List(Tag),)

    app = App(Todo)

Everything exported here is public API. Runtime internals (nodes, signals, the
SQL compiler) stay importable from their submodules but are
deliberately kept out of ``import *``.
"""

from __future__ import annotations

from .errors import DslError, OneFrameworkError, SchemaError, ValidationError
from .device import OnDevice, action
from .model.expr import UNSET, expr, item, record, view
from .model.fields import (
    Binary,
    Boolean,
    String,
    Text,
    Html,
    Email,
    Phone,
    Url,
    Password,
    Barcode,
    Percent,
    Rating,
    Image,
    Signature,
    Uuid,
    Color,
    Date,
    Datetime,
    Duration,
    Float,
    GeoPoint,
    Integer,
    Json,
    Many2many,
    Many2one,
    One2one,
    Monetary,
    One2many,
    Selection,
    Time,
    register_widget,
)
from .model.meta import Model
from .modules import Module, discover, load_all
from .app import App
from .ui.components import (
    Accordion, Button, Col, Delete, Filter, Create, Group, List, Logic, Menu, Open, Repeat, Row, Save, Search,
    Section,
    Sort,
    Icon, Label, Pill, Set, Tab, Tabs,
)
from .ui.screen import Screen
from .ui.view import View

__version__ = "0.1.0"

__all__ = [
    "expr",
    # declarative core
    "Model",
    "View",
    "App",
    "Screen",
    # modules
    "load_all",
    "discover",
    "Module",
    "register_widget",
    # fields -- text
    "String",
    "Text",
    "Html",
    "Email",
    "Phone",
    "Url",
    "Password",
    "Barcode",
    "Percent",
    "Rating",
    "Image",
    "Signature",
    "Uuid",
    # fields -- numeric
    "Integer",
    "Json",
    "Float",
    "Monetary",
    "Duration",
    # fields -- other scalars
    "Boolean",
    "Selection",
    "Color",
    # fields -- temporal
    "Date",
    "Datetime",
    "Time",
    # fields -- binary
    "Binary",
    # fields -- geo
    "GeoPoint",
    # fields -- relational
    "Many2one",
    "One2one",
    "One2many",
    "Many2many",
    # components
    "Row",
    "Repeat",
    "Col",
    "Group",
    "Accordion",
    "Section",
    "Tabs",
    "Label",
    "Pill",
    "Icon",
    "Set",
    "Tab",
    "List",
    "Menu",
    "Button",
    "Search",
    "Filter",
    "Sort",
    # actions
    "Delete",
    "Open",
    "Create",
    "Save",
    "Logic",
    # context proxies + sentinel
    "OnDevice",
    "action",
    "record",
    "view",
    "item",
    "UNSET",
    # errors worth catching
    "OneFrameworkError",
    "DslError",
    "SchemaError",
    "ValidationError",
]
