from oneframework import (
    Color,
    Email,
    Many2many,
    Many2one,
    Model,
    One2many,
    One2one,
    Phone,
    String,
    Text,
)


class Company(Model):
    name = String("Компания", required=True)
    site = String("Сайт")


class Passport(Model):
    """The other side of a real One2one -- one holder, enforced in SQL."""

    number = String("Номер", required=True)
    issued = String("Кем выдан")


class Skill(Model):
    name = String("Навык", required=True)
    color = Color("Цвет")


class Contact(Model):
    name = String("Имя", required=True)
    mail = Email("Почта")
    tel = Phone("Телефон")
    company = Many2one(Company, "Компания")
    passport = One2one(Passport, "Паспорт")
    skills = Many2many(Skill, "Навыки")
    notes = One2many("Note", "contact", "Заметки")


class Note(Model):
    text = String("Заметка", required=True)
    body = Text("Текст")
    contact = Many2one(Contact, "Контакт")
