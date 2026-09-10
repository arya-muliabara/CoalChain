from datetime import date, timedelta
from sqlalchemy import select
from .database import Record, now
from .security import scope_query
from .business import settings, contract_totals, serialize, FINAL

def dashboard(db, user, period=None, site=None, contractor=None):
    period = period or date.today().strftime("%Y-%m")
    q = scope_query(user, select(Record), Record)
    if site:
        q = q.where(Record.site_id == site)
    if contractor:
        q = q.where(Record.contractor_id == contractor)
    rows = list(db.scalars(q))
    def group(kind, monthly=False, final=False):
        return [r for r in rows if r.kind == kind and r.status not in ("CANCELLED", "REJECTED")
                and (not final or r.status in FINAL)
                and (not monthly or (r.data.get("date", r.data.get("period", r.data.get("start", ""))) or "").startswith(period))]
    cfg = settings(db)
    prod = group("production", True, True)
    plans = [p for p in group("plans", False, True) if p.data["level"] == "Monthly" and p.data["start"][:7] <= period <= p.data["end"][:7]]
    coal = sum(r.data["quantity"] for r in prod if r.data["activity"] == "Coal Getting")
    ob = sum(r.data["quantity"] for r in prod if r.data["activity"] == "OB Removal")
    coal_plan = sum(r.data["quantity"] for r in plans if r.data["activity"] == "Coal Getting")
    ob_plan = sum(r.data["quantity"] for r in plans if r.data["activity"] == "OB Removal")
    scheduled = sum(r.data["scheduled"] for r in prod)
    available = scheduled - sum(r.data["breakdown"] + r.data["maintenance"] for r in prod)
    working = sum(r.data["working"] for r in prod)
    pa = available / scheduled * 100 if scheduled else 0
    ua = working / available * 100 if available else 0
    fuel = sum(r.data["liter"] for r in group("fuel", True, True))
    ob_keys = {(r.data["date"], r.data["equipment_id"]) for r in prod if r.data["activity"] == "OB Removal"}
    ob_fuel = sum(r.data["liter"] for r in group("fuel", True, True) if (r.data["date"], r.data["equipment_id"]) in ob_keys)
    fuel_ratio = ob_fuel / ob if ob else 0
    claims = group("claims", True, True)
    contract_rows, alerts = [], []
    for row in group("contracts", final=True):
        t = contract_totals(db, row)
        utilization = t["reserved"] / t["value"] * 100 if t["value"] else 0
        contract_rows.append({**serialize(row), **t, "utilization": round(utilization, 1)})
        if utilization > cfg["contract_warning"]:
            alerts.append(dict(type="warning", title="Utilisasi kontrak", detail=f'{row.data["name"]}: {utilization:.1f}% terpakai / direservasi', module="contracts", id=row.id))
        days = (date.fromisoformat(t["end"]) - date.today()).days
        if days < cfg["expiry_days"]:
            alerts.append(dict(type="warning", title="Masa berlaku kontrak", detail=f'{row.data["name"]}: {days} hari tersisa', module="contracts", id=row.id))
    for row in group("reconciliations"):
        if row.data.get("exception") and row.status not in FINAL:
            alerts.append(dict(type="danger", title="Selisih quantity", detail=f'{row.id}: variance {row.data["variance"]:+.2f}%', module="reconciliations", id=row.id))
    for row in group("hse", True):
        if row.data["type"] not in ("Inspection", "Safety Observation") and row.status not in FINAL:
            alerts.append(dict(type="danger", title=row.data["type"], detail=row.data["description"], module="hse", id=row.id))
    month_start = date.fromisoformat(period + "-01")
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    elapsed = max(0, min((date.today() - month_start).days + 1, month_end.day)) / month_end.day
    for label, actual, target in [("Coal", coal, coal_plan), ("Overburden", ob, ob_plan)]:
        if target and elapsed and actual / (target * elapsed) * 100 < cfg["production_warning"]:
            alerts.append(dict(type="warning", title=f"{label} di bawah target MTD", detail=f'{actual / (target * elapsed) * 100:.1f}% dari target sampai hari ini', module="production"))
    if scheduled and pa < cfg["pa_warning"]:
        alerts.append(dict(type="warning", title="Equipment availability", detail=f'PA {pa:.1f}% di bawah {cfg["pa_warning"]}%', module="equipment"))
    if ob and fuel_ratio > cfg["fuel_standard"] * (1 + cfg["fuel_excess"] / 100):
        alerts.append(dict(type="warning", title="Fuel ratio melewati standar", detail=f'{fuel_ratio:.2f} L/BCM', module="fuel"))
    trend = []
    for day in range(1, month_end.day + 1):
        day_rows = [r for r in prod if r.data["date"] == f"{period}-{day:02d}"]
        trend.append(dict(day=day, coal=sum(r.data["quantity"] for r in day_rows if r.data["activity"] == "Coal Getting"), ob=sum(r.data["quantity"] for r in day_rows if r.data["activity"] == "OB Removal"), target=coal_plan / month_end.day))
    equipment = group("equipment")
    fleet = {status: sum(r.data["operating_status"] == status for r in equipment) for status in ["Working", "Standby", "Breakdown", "Maintenance", "Waiting", "Idle"]}
    ranking = sorted([serialize(r) for r in group("scorecards", True, True)], key=lambda r: r["score"], reverse=True)
    pending = [serialize(r) for r in rows if r.status == "SUBMITTED" and (user.role == "System Administrator" or r.workflow[r.stage] == user.role)]
    hse = group("hse", True, True)
    manhours = sum(r.data["hours"] for r in group("manpower", True))
    lti = sum(r.data["type"] == "LTI" for r in hse)
    recordable = sum(r.data["type"] in ("LTI", "Fatality", "Medical Treatment") for r in hse)
    costs = []
    for activity in ["OB Removal", "Coal Getting", "Coal Hauling"]:
        activity_prod = [r for r in prod if r.data["activity"] == activity]
        ids = {r.id for r in activity_prod}
        rec_ids = {r.id for r in group("reconciliations") if r.data["production_id"] in ids}
        actual = sum(r.data["net"] for r in claims if r.data["reconciliation_id"] in rec_ids)
        volume = sum(r.data["quantity"] for r in activity_prod)
        budget = sum(r.data["budget"] for r in plans if r.data["activity"] == activity)
        costs.append(dict(activity=activity, budget=budget, actual=actual, forecast=actual/elapsed if elapsed else 0, variance=budget-actual, quantity=volume, unit_cost=actual/volume if volume else 0))
    return dict(period=period, coal=coal, ob=ob, coal_plan=coal_plan, ob_plan=ob_plan, pa=round(pa, 1), ua=round(ua, 1),
                stripping_ratio=round(ob/coal, 2) if coal else 0, fuel=fuel, fuel_ratio=round(fuel_ratio, 2), cost=sum(r.data["net"] for r in claims),
                fleet=fleet, fleet_total=len(equipment), trend=trend, ranking=ranking, contracts=contract_rows,
                alerts=alerts, pending=pending, costs=costs, manhours=manhours,
                ltifr=round(lti*1_000_000/manhours, 2) if manhours else None,
                trifr=round(recordable*1_000_000/manhours, 2) if manhours else None,
                total_contractors=len(group("contractors")), updated_at=now().isoformat())

