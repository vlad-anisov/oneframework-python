from oneframework import Email, Image, Many2one, Model, One2one, Phone, String, Text


class Company(Model):
    name = String("Company", required=True)
    site = String("Website")


class Passport(Model):
    """Deliberately 1:1 with Person -- one passport, one holder."""

    number = String("Number", required=True)
    issued = String("Issued by")


class Person(Model):
    name = String("Name", required=True)
    mail = Email("E-mail")
    tel = Phone("Phone")
    about = Text("About")
    photo = Image("Photo")
    company = Many2one(Company, "Company")
    passport = One2one(Passport, "Passport")
