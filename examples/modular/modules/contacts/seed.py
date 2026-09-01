from .models import Company, Person


def seed(db):
    acme = db.create(Company, {"name": "Acme", "site": "acme.example"})
    db.create(Person, {"name": "Ann Lee", "mail": "ann@acme.example",
                       "tel": "+1 555 0100", "company": acme})
    db.create(Person, {"name": "Bob Ray", "mail": "bob@acme.example", "company": acme})
