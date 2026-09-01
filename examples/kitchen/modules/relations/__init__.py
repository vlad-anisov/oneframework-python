"""Relations: Many2one, One2many and Many2many on one record."""

from oneframework import Screen

from .models import Company, Contact, Note, Passport, Skill
from .views import ContactDetail, ContactItem, Contacts

__all__ = ["Company", "Contact", "Note", "Passport", "Skill",
           "ContactDetail", "ContactItem", "Contacts"]

SCREEN = Screen(Contacts, label="Связи", icon="layers", sequence=30)
