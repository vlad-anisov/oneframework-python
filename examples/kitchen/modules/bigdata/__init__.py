"""Big data: what a list does when it does not fit in memory or on screen."""

from oneframework import Screen

from .models import Row_
from .views import BigData, BigDetail, BigItem

__all__ = ["Row_", "BigData", "BigDetail", "BigItem"]

SCREEN = Screen(BigData, label="Данные", icon="bar_chart", sequence=50)
