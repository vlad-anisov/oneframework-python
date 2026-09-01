"""Catalog: the table presentation of a list."""

from oneframework import Screen

from .models import Product
from .views import Catalog, ProductDetail, ProductItem

__all__ = ["Product", "Catalog", "ProductDetail", "ProductItem"]

SCREEN = Screen(Catalog, label="Каталог", icon="grid_view", sequence=20)
