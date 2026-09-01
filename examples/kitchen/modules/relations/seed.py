from relations.models import Company, Contact, Note, Passport, Skill

SKILLS = [("Python", "#3776AB"), ("SQL", "#00758F"), ("UI", "#B58392"),
          ("Android", "#3DDC84")]


def seed(db):
    acme = db.create(Company, {"name": "Acme", "site": "acme.example"})
    globex = db.create(Company, {"name": "Globex", "site": "globex.example"})
    skills = [db.create(Skill, {"name": n, "color": c}) for n, c in SKILLS]
    field = Contact._fields["skills"]

    people = [
        ("Аня Ли", "anna@acme.example", "+7 900 000-00-01", acme, "45 12 345678"),
        ("Борис Рей", "boris@globex.example", "+7 900 000-00-02", globex, "45 12 998877"),
        ("Вера Ким", "vera@acme.example", "+7 900 000-00-03", acme, None),
    ]
    for index, (name, mail, tel, company, passport_no) in enumerate(people):
        passport = (
            db.create(Passport, {"number": passport_no, "issued": "ОВД"})
            if passport_no
            else None
        )
        contact = db.create(
            Contact,
            {"name": name, "mail": mail, "tel": tel,
             "company": company, "passport": passport},
        )
        db.set_many2many(field, contact, skills[: index + 2])
        for n in range(index + 1):
            db.create(
                Note,
                {"text": f"Звонок {n + 1}", "body": "Договорились созвониться позже.",
                 "contact": contact},
            )
