"""Contacts: people and their companies."""

from oneframework import Screen

from .models import Company, Person
from .views import ContactsBoard, PersonDetail, PersonItem

__all__ = ["Company", "Person", "ContactsBoard", "PersonDetail", "PersonItem"]

#: installing the module is what puts this section in the navigation
SCREEN = Screen(ContactsBoard, label="Контакты", icon="group")
