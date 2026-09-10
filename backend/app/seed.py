"""Synthetic, opt-in demo data. Never called in production unless MCMS_DEMO=true."""
import os
import calendar
from datetime import date
from sqlalchemy import select
from .database import User
from .catalog import CATALOG, ROLES
from .business import save_record, transition
from .security import hash_password

def seed(db):
    admin = db.get(User, "USR-ADMIN")
    today = date.today()
    period = today.strftime("%Y-%m")
    start, end = period + "-01", f"{period}-{calendar.monthrange(today.year, today.month)[1]}"
    def add(kind, data, final=True):
        payload = {}
        for f in CATALOG[kind]["fields"]:
            if f["key"] in data:
                payload[f["key"]] = data[f["key"]]
            elif f["required"]:
                payload[f["key"]] = 0 if f["type"] in ("number", "signed") else f["options"][0] if f["options"] else "Demo"
        row = save_record(db, admin, kind, payload)
        if final and row.workflow:
            transition(db, admin, row, "submit", "Demo seed", row.version)
            while row.status == "SUBMITTED":
                transition(db, admin, row, "approve", "Demo seed", row.version)
        db.flush()
        return row
    site = add("sites", dict(name="Batu Ampar", company="PT MOne Energi Nusantara", location="Kalimantan Timur"))
    pit = add("pits", dict(name="Pit North", site_id=site.id, area="North Mining Area", block="N-01", seam="A1"))
    for name, typ in [("ROM North", "ROM"), ("Disposal A", "Disposal"), ("Fuel Station 01", "Fuel Station"), ("Stockpile Main", "Stockpile")]:
        add("locations", dict(name=name, site_id=site.id, type=typ, distance=8.5))
    contractors = []
    for n, name in enumerate(["PT Bara Karya Mandiri", "PT Cipta Tambang Utama", "PT Nusantara Mining"]):
        ct = add("contractors", dict(name=name, vendor_id=f"V-00{n+1}", site_id=site.id, address="Kalimantan Timur", contact=f"operations{n+1}@example.com", owner_pic="Tim Mining Operation", contractor_pic=f"Supervisor {n+1}"))
        contractors.append(ct)
        common = dict(site_id=site.id, contractor_id=ct.id)
        contract = add("contracts", dict(**common, name=f"MC-{today.year}-00{n+1}", type="Mining Services", start=f"{today.year}-01-01", end=f"{today.year}-12-31", value=30_000_000_000, quantity_limit=3_000_000, scope="OB removal dan coal getting", payment_terms="30 hari setelah invoice verified", retention=5))
        for activity, unit, rate, target, budget in [("OB Removal", "BCM", 32000, 420000, 13440000000), ("Coal Getting", "Ton", 24000, 62000, 1488000000)]:
            add("rates", dict(**common, contract_id=contract.id, activity=activity, unit=unit, rate=rate, start=f"{today.year}-01-01", end=f"{today.year}-12-31", min_distance=0, max_distance=100))
            add("plans", dict(**common, name=f"{activity} / {period}", pit_id=pit.id, activity=activity, level="Monthly", start=start, end=end, quantity=target, unit=unit, budget=budget))
        equipment = []
        for e in range(6):
            equipment.append(add("equipment", dict(**common, name=f"{'EX' if e<2 else 'DT'}-{n+1}{e+1:02d}", category="Excavator" if e<2 else "Dump Truck", brand="Komatsu PC1250" if e<2 else "Caterpillar 777", serial=f"SN-{n}-{e}", capacity=7 if e<2 else 90, ownership="Owned", commission=f"{today.year}-01-01", operating_status="Breakdown" if e == 5 and n == 1 else "Standby" if e == 4 else "Working")))
        first = None
        for day in range(1, min(today.day, 10) + 1):
            day_date = f"{period}-{day:02d}"
            for index, (activity, material, unit, base) in enumerate([("OB Removal", "Overburden", "BCM", 14000), ("Coal Getting", "Coal", "Ton", 2100)]):
                quantity = base + ((day * 173 + n * 137) % 1000) - 400
                row = add("production", dict(**common, date=day_date, shift="Day", pit_id=pit.id, block="N-01", seam="A1", activity=activity, material=material, loading="Pit North", dumping="Disposal A" if index == 0 else "ROM North", equipment_id=equipment[index].id, quantity=quantity, unit=unit, distance=3.5, working=9, standby=2, breakdown=.5, maintenance=.5, scheduled=12), final=not(day==min(today.day,10) and n==2))
                if day == 1 and index == 0:
                    first = row
            add("fuel", dict(**common, date=day_date, equipment_id=equipment[0].id, station="Fuel Station 01", liter=9500+n*200, hour_meter=1000+day*12, operator=f"Operator {n+1}", fuel_truck="FT-01", reference=f"FUEL-{n}-{day}"))
            add("manpower", dict(**common, date=day_date, shift="Day", position="Mining crew", planned=60, actual=58, hours=580))
        score = add("scorecards", dict(**common, period=period, production=98-n*4, equipment=95-n*2, productivity=96-n*3, fuel=94+n, hse=100-n*4, quality=98, compliance=99-n, evidence="Data simulasi untuk demonstrasi scorecard."))
        if first and first.status == "VERIFIED":
            survey_qty = first.data["quantity"] - 60
            survey = add("surveys", dict(**common, date=start, period=period, pit_id=pit.id, block="N-01", activity="OB Removal", material="Overburden", beginning=500000, ending=500000-survey_qty, quantity=survey_qty, unit="BCM"))
            rec = add("reconciliations", dict(**common, production_id=first.id, survey_id=survey.id, owner_quantity=first.data["quantity"]-25, approved_quantity=survey_qty, resolution="Selisih dalam toleransi survei."))
            claim = add("claims", dict(**common, contract_id=contract.id, period=period, reconciliation_id=rec.id, scorecard_id=score.id, deduction=0), final=n==0)
            if n==0:
                add("invoices", dict(**common, name=f"INV-{period}-001", claim_id=claim.id, date=start, due=end, amount=claim.data["net"]))
        if n==1:
            add("hse", dict(**common, date=today.isoformat(), type="Near Miss", location="Hauling Road KM 3", description="Jarak aman antar unit tidak terjaga saat pergantian shift.", action="Briefing operator dan inspeksi rambu jalur.", lost_hours=0), final=False)
    demo_password = os.getenv("MCMS_DEMO_PASSWORD")
    if demo_password and len(demo_password) >= 12:
        for index, role in enumerate(ROLES[1:]):
            slug = role.lower().replace(" ", ".")
            db.add(User(id=f"USR-DEMO-{index}", email=slug+"@coalchain.local", name=role, role=role,
                        site_id=site.id, contractor_id=contractors[0].id if role.startswith("Contractor") else None,
                        password_hash=hash_password(demo_password)))
    db.commit()

