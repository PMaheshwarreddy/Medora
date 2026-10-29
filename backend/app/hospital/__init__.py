"""The hospital admin portal (a tenant's own back office), kept apart from
the company back office in `routers/admin.py`.

Hospital people (hospital admins, doctors, staff) have their own accounts
and sessions (`models.HospitalUser`, `HospitalSession`), separate from the
company's back-office accounts: a hospital login can never open the company
back office, and the company's open registration never creates hospital
accounts. Every query here is scoped to the signed-in person's own hospital
(`service.scope`), never to a hospital named in the request.
"""
