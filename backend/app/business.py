import copy
import math
import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException
from sqlalchemy import select
from .catalog import CATALOG, DEFAULT_SETTINGS, ADMIN
from .database import Record, Config, Audit, now
from .security import visible, can_write, scope_query

FINAL = {"APPROVED", "VERIFIED", "CLOSED"}
INACTIVE = {"CANCELLED", "REJECTED"}

def fail(message, status=422):
    raise HTTPException(status, message)

def money(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def settings(db):
    entry = db.get(Config, "settings")
    return copy.deepcopy(entry.value if entry else DEFAULT_SETTINGS)

def all_rows(db, kind, exclude=None):
    q = select(Record).where(Record.kind == kind, Record.status.not_in(INACTIVE))
    if exclude:
        q = q.where(Record.id != exclude)
    return list(db.scalars(q))

def get_record(db, user, record_id, kind=None, lock=False):
    q = select(Record).where(Record.id == record_id)
    if lock:
        q = q.with_for_update()
    row = db.scalar(q.execution_options(populate_existing=True))
    if not row or (kind and row.kind != kind) or not visible(user, row):
        fail("Data tidak ditemukan atau di luar hak akses Anda.", 404)
    return row

def serialize(row):
    return {**row.data, "id": row.id, "kind": row.kind, "status": row.status, "stage": row.stage,
            "workflow": row.workflow, "version": row.version, "created_by": row.created_by,
            "created_at": row.created_at.isoformat(), "modified_by": row.modified_by,
            "modified_at": row.modified_at.isoformat(),
            "next_role": row.workflow[row.stage] if row.status == "SUBMITTED" and row.stage < len(row.workflow) else None}

def audit(db, user, action, row=None, before=None, reason="", after=None):
    db.add(Audit(record_id=row.id if row else None, actor=user.email, action=action,
                 before=before or {}, after=after if after is not None else (serialize(row) if row else {}), reason=reason))

def contract_totals(db, contract, exclude=None):
    amendments = [r for r in all_rows(db, "amendments") if r.data["contract_id"] == contract.id and r.status == "APPROVED"]
    value = money(contract.data["value"] + sum(r.data["value_change"] for r in amendments))
    quantity = contract.data["quantity_limit"] + sum(r.data["quantity_change"] for r in amendments)
    end = sorted(amendments, key=lambda r: r.modified_at)[-1].data["new_end"] if amendments else contract.data["end"]
    claims = [r for r in all_rows(db, "claims", exclude) if r.data["contract_id"] == contract.id]
    reserved = money(sum(r.data["net"] for r in claims))
    used = money(sum(r.data["net"] for r in claims if r.status in FINAL))
    return dict(value=value, quantity=quantity, end=end, reserved=reserved, utilized=used,
                remaining=money(value - reserved), used_quantity=sum(r.data["quantity"] for r in claims))

def validate(db, user, kind, incoming, record_id=None):
    if kind not in CATALOG:
        fail("Modul tidak ditemukan.", 404)
    data = {}
    for f in CATALOG[kind]["fields"]:
        key, typ = f["key"], f["type"]
        value = incoming.get(key)
        if value is None or value == "":
            if f["required"]:
                fail(f'{f["label"]} wajib diisi.')
            data[key] = None if typ in ("reference", "date", "month") else (0 if typ in ("number", "signed") else "")
            continue
        if typ in ("number", "signed"):
            try:
                value = float(value)
            except (ValueError, TypeError):
                fail(f'{f["label"]} harus berupa angka.')
            if not math.isfinite(value) or abs(value) > 1e15 or (typ == "number" and value < 0):
                fail(f'{f["label"]} di luar rentang yang diizinkan.')
        else:
            value = str(value).strip()
            if len(value) > (10000 if typ == "textarea" else 500):
                fail(f'{f["label"]} terlalu panjang.')
        if typ == "select" and value not in f["options"]:
            fail(f'{f["label"]} tidak valid.')
        if typ in ("date", "month"):
            try:
                date.fromisoformat(value + "-01" if typ == "month" else value)
                if len(value) != (7 if typ == "month" else 10):
                    raise ValueError()
            except ValueError:
                fail(f'{f["label"]} tidak valid.')
        if typ == "reference":
            ref = get_record(db, user, value, f["ref"])
            if ref.status in INACTIVE:
                fail(f'{f["label"]} sudah dibatalkan.')
            if incoming.get("contractor_id") and ref.contractor_id and ref.contractor_id != incoming["contractor_id"]:
                fail(f'{f["label"]} bukan milik kontraktor yang dipilih.')
            if incoming.get("site_id") and ref.site_id and ref.site_id != incoming["site_id"]:
                fail(f'{f["label"]} bukan milik site yang dipilih.')
        data[key] = value
    if user.site_id and data.get("site_id") != user.site_id and user.role != ADMIN:
        fail("Site di luar hak akses.", 403)
    if user.contractor_id and data.get("contractor_id") != user.contractor_id and kind not in ("sites", "pits", "locations", "contractors"):
        fail("Kontraktor di luar hak akses.", 403)
    if data.get("start") and data.get("end") and data["end"] < data["start"]:
        fail("Tanggal akhir tidak boleh lebih awal dari tanggal mulai.")
    if kind in ("production", "hauling", "surveys", "plans") and data["quantity"] <= 0:
        fail("Quantity harus lebih besar dari nol.")
    if kind in ("production", "hauling", "fuel"):
        equipment = get_record(db, user, data["equipment_id"], "equipment")
        if equipment.data["commission"] > data["date"]:
            fail("Equipment belum aktif pada tanggal transaksi.")
    if kind == "production":
        total = sum(data[k] for k in ("working", "standby", "breakdown", "maintenance"))
        if not 0 < data["scheduled"] <= 24 or abs(total - data["scheduled"]) > .01:
            fail("Working + standby + breakdown + maintenance harus sama dengan scheduled hours (maksimum 24).")
        expected = "BCM" if data["material"] in ("Overburden", "Topsoil") else "Ton" if data["material"] == "Coal" else None
        if expected and data["unit"] != expected:
            fail(f"Satuan produksi material ini harus {expected}; jarak dihitung terpisah saat billing.")
        activity_material = {"OB Removal": "Overburden", "OB Hauling": "Overburden", "Coal Getting": "Coal", "Coal Hauling": "Coal", "Topsoil Removal": "Topsoil"}
        if data["activity"] in activity_material and data["material"] != activity_material[data["activity"]]:
            fail("Material tidak cocok dengan aktivitas.")
        available = data["scheduled"] - data["breakdown"] - data["maintenance"]
        data.update(pa=round(available / data["scheduled"] * 100, 2), ua=round(data["working"] / available * 100, 2) if available else 0,
                    productivity=round(data["quantity"] / data["working"], 2) if data["working"] else 0)
    if kind == "surveys":
        data["difference"] = abs(data["ending"] - data["beginning"])
        if abs(data["difference"] - data["quantity"]) > .01:
            fail("Survey quantity harus sama dengan selisih absolut volume awal dan akhir.")
        if data["date"][:7] != data["period"]:
            fail("Tanggal survey harus berada dalam periode survey.")
    if kind == "fuel" and data["liter"] <= 0:
        fail("Liter harus lebih besar dari nol.")
    if kind == "rates":
        contract = get_record(db, user, data["contract_id"], "contracts", lock=True)
        if data["rate"] <= 0 or data["max_distance"] < data["min_distance"]:
            fail("Rate harus positif dan rentang jarak valid.")
        for r in all_rows(db, "rates", record_id):
            d = r.data
            if d["contract_id"] == data["contract_id"] and d["activity"] == data["activity"] and d["unit"] == data["unit"] and max(d["start"], data["start"]) <= min(d["end"], data["end"]) and max(d["min_distance"], data["min_distance"]) <= min(d["max_distance"], data["max_distance"]):
                fail("Rate untuk aktivitas, satuan, tanggal, dan jarak ini tumpang tindih.")
    if kind == "contracts":
        if data["value"] <= 0 or data["quantity_limit"] <= 0 or data["retention"] > 100:
            fail("Nilai/batas quantity harus positif dan retensi maksimum 100%.")
    if kind == "amendments":
        contract = get_record(db, user, data["contract_id"], "contracts", lock=True)
        totals = contract_totals(db, contract)
        if contract.status != "APPROVED" or totals["value"] + data["value_change"] < totals["reserved"] or totals["quantity"] + data["quantity_change"] < totals["used_quantity"]:
            fail("Amendment membutuhkan kontrak approved dan tidak boleh mengurangi batas di bawah klaim yang sudah ada.")
        if data["new_end"] < contract.data["start"]:
            fail("Tanggal akhir amendment tidak valid.")
    if kind == "reconciliations":
        prod = get_record(db, user, data["production_id"], "production", lock=True)
        survey = get_record(db, user, data["survey_id"], "surveys", lock=True)
        if prod.status != "VERIFIED" or survey.status != "APPROVED":
            fail("Rekonsiliasi membutuhkan DPR VERIFIED dan survei APPROVED.")
        if any(prod.data[k] != survey.data[k] for k in ("pit_id", "block", "activity", "material", "unit")) or prod.data["date"][:7] != survey.data["period"]:
            fail("Pit, block, aktivitas, material, satuan, dan periode DPR/survei harus cocok.")
        others = all_rows(db, "reconciliations", record_id)
        if any(r.data["production_id"] == prod.id for r in others):
            fail("DPR ini sudah memiliki rekonsiliasi.")
        allocated = sum(r.data["approved_quantity"] for r in others if r.data["survey_id"] == survey.id)
        if data["approved_quantity"] <= 0 or allocated + data["approved_quantity"] > survey.data["quantity"]:
            fail("Commercial quantity harus positif dan total alokasi tidak boleh melebihi survei final.")
        data["variance"] = round((data["approved_quantity"] - prod.data["quantity"]) / prod.data["quantity"] * 100, 2)
        data["owner_variance"] = round((data["owner_quantity"] - prod.data["quantity"]) / prod.data["quantity"] * 100, 2)
        data["exception"] = max(abs(data["variance"]), abs(data["owner_variance"])) > settings(db)["tolerance"]
    if kind == "scorecards":
        weights = settings(db)["weights"]
        if any(data[k] > 200 for k in weights):
            fail("Achievement KPI maksimum 200%.")
        data["weights"] = weights
        data["score"] = round(sum(data[k] * v / 100 for k, v in weights.items()), 2)
    if kind == "rules" and data["percent"] > 100:
        fail("Persentase maksimum 100%.")
    if kind == "claims":
        contract = get_record(db, user, data["contract_id"], "contracts", lock=True)
        rec = get_record(db, user, data["reconciliation_id"], "reconciliations", lock=True)
        prod = get_record(db, user, rec.data["production_id"], "production")
        if contract.status != "APPROVED" or rec.status != "APPROVED" or prod.status != "VERIFIED":
            fail("Claim hanya dapat memakai kontrak dan rekonsiliasi approved serta DPR verified.")
        if any(r.data["reconciliation_id"] == rec.id for r in all_rows(db, "claims", record_id)):
            fail("Quantity rekonsiliasi ini sudah digunakan oleh claim lain.")
        totals = contract_totals(db, contract, record_id)
        if not contract.data["start"] <= prod.data["date"] <= totals["end"]:
            fail("Kontrak tidak aktif pada tanggal produksi.")
        if data["period"] != prod.data["date"][:7]:
            fail("Periode claim harus sama dengan periode produksi.")
        rate_candidates = [r for r in all_rows(db, "rates") if r.status == "APPROVED" and r.data["contract_id"] == contract.id and r.data["activity"] == prod.data["activity"] and r.data["start"] <= prod.data["date"] <= r.data["end"] and r.data["min_distance"] <= prod.data["distance"] <= r.data["max_distance"] and r.data["unit"] in (prod.data["unit"], prod.data["unit"] + "-KM")]
        if len(rate_candidates) != 1:
            fail("Harus ada tepat satu rate approved yang cocok dengan aktivitas, tanggal, satuan, dan jarak produksi.")
        rate = rate_candidates[0]
        quantity = rec.data["approved_quantity"]
        distance = prod.data["distance"] if rate.data["unit"].endswith("-KM") else 1
        if distance <= 0:
            fail("Jarak harus positif untuk rate berbasis kilometer.")
        gross = money(Decimal(str(quantity)) * Decimal(str(rate.data["rate"])) * Decimal(str(distance)))
        incentive = penalty = 0
        evidence = []
        rules = [r for r in all_rows(db, "rules") if r.status == "APPROVED" and r.data["contract_id"] == contract.id]
        if rules and not data["scorecard_id"]:
            fail("Kontrak memiliki aturan penalty/incentive; pilih scorecard approved.")
        if data["scorecard_id"]:
            score = get_record(db, user, data["scorecard_id"], "scorecards")
            if score.status != "APPROVED" or score.data["period"] != data["period"]:
                fail("Scorecard harus approved dan sesuai periode claim.")
            for rule in rules:
                rd = rule.data
                actual = score.data[rd["metric"]]
                triggered = actual < rd["threshold"] if rd["operator"] == "below" else actual > rd["threshold"]
                amount = money(gross * rd["percent"] / 100) if triggered else 0
                evidence.append(dict(rule_id=rule.id, name=rd["name"], metric=rd["metric"], actual=actual, threshold=rd["threshold"], operator=rd["operator"], percent=rd["percent"], kind=rd["kind"], amount=amount))
                if rd["kind"] == "Penalty":
                    penalty += amount
                else:
                    incentive += amount
        if data["deduction"] > 0 and not data["deduction_reason"]:
            fail("Deduction membutuhkan alasan.")
        retention = money(gross * contract.data["retention"] / 100)
        net = money(gross + incentive - penalty - data["deduction"] - retention)
        if net <= 0 or net > totals["remaining"] or totals["used_quantity"] + quantity > totals["quantity"]:
            fail("Net claim harus positif dan tidak boleh melebihi sisa nilai/quantity kontrak. Buat amendment approved terlebih dahulu.")
        data.update(quantity=quantity, rate=rate.data["rate"], rate_id=rate.id, unit=rate.data["unit"], distance=distance, gross=gross, penalty=money(penalty), incentive=money(incentive), retention=retention, net=net, evidence=evidence)
    if kind == "invoices":
        claim = get_record(db, user, data["claim_id"], "claims", lock=True)
        if claim.status != "APPROVED":
            fail("Invoice membutuhkan progress claim APPROVED.")
        used = sum(r.data["amount"] for r in all_rows(db, "invoices", record_id) if r.data["claim_id"] == claim.id)
        if data["amount"] <= 0 or money(used + data["amount"]) > claim.data["net"]:
            fail("Total invoice tidak boleh melebihi net claim approved.")
        if data["due"] < data["date"]:
            fail("Jatuh tempo tidak boleh mendahului tanggal invoice.")
    if kind == "stockpiles":
        if data["capacity"] <= 0 or data["minimum_stock"] < 0 or data["opening_balance"] < 0:
            fail("Kapasitas dan saldo awal stockpile harus bernilai positif.")
        if data["minimum_stock"] > data["capacity"] or data["opening_balance"] > data["capacity"]:
            fail("Minimum stock dan saldo awal tidak boleh melebihi kapasitas stockpile.")
    if kind == "hauling":
        if data["material"] != "Coal" or data["unit"] != "Ton":
            fail("Coal hauling hanya menerima material Coal dalam satuan Ton.")
        if data["distance"] <= 0 or data["trips"] <= 0 or data["quantity"] <= 0:
            fail("Jarak, jumlah rit/voyage, dan tonase hauling harus lebih besar dari nol.")
        stockpile = get_record(db, user, data["destination_stockpile_id"], "stockpiles")
        if stockpile.data["site_id"] != data["site_id"]:
            fail("Stockpile tujuan harus berada pada site yang sama.")
        data["ton_km"] = round(data["quantity"] * data["distance"], 2)
        data["average_load"] = round(data["quantity"] / data["trips"], 2)
    if kind == "stockpile_movements":
        stockpile = get_record(db, user, data["stockpile_id"], "stockpiles")
        if stockpile.data["site_id"] != data["site_id"]:
            fail("Stockpile harus berada pada site yang sama.")
        if data["quantity"] <= 0 or data["unit"] != "Ton":
            fail("Mutasi stockpile harus bernilai positif dalam satuan Ton.")
        if data["direction"] == "OUT" and stockpile_balance(db, data["stockpile_id"], record_id) + .0001 < data["quantity"]:
            fail("Saldo stockpile tidak mencukupi untuk mutasi OUT.")
    return data

def natural_key(kind, data):
    fields = {"production": ["date", "shift", "equipment_id", "activity", "pit_id"], "hauling": ["date", "equipment_id", "origin_location_id", "destination_stockpile_id", "transport_reference"], "stockpiles": ["code"], "stockpile_movements": ["date", "stockpile_id", "direction", "reference"], "fuel": ["contractor_id", "reference"],
              "scorecards": ["contractor_id", "site_id", "period"], "equipment": ["name"], "contracts": ["name"],
              "contractors": ["vendor_id"], "invoices": ["contractor_id", "name"]}.get(kind)
    return kind + ":" + "|".join(str(data[k]).strip().lower() for k in fields) if fields else None

def save_record(db, user, kind, payload, existing=None, reason=""):
    if not can_write(user, kind):
        fail("Anda tidak memiliki hak untuk mengubah modul ini.", 403)
    if existing and existing.status not in ("DRAFT", "RETURNED", "REJECTED", "ACTIVE"):
        fail("Transaksi terkunci. Gunakan permintaan reopen untuk data final.", 409)
    data = validate(db, user, kind, payload, existing.id if existing else None)
    key = natural_key(kind, data)
    duplicate = db.scalar(select(Record).where(Record.natural_key == key)) if key else None
    if duplicate and (not existing or duplicate.id != existing.id):
        fail("Transaksi duplikat: kombinasi identitas sudah digunakan.", 409)
    if existing and existing.status == "ACTIVE" and has_dependents(db, existing):
        for critical in ("site_id", "contractor_id", "commission"):
            if existing.data.get(critical) != data.get(critical):
                fail("Scope atau tanggal aktif master tidak dapat diubah setelah direferensikan transaksi.", 409)
    before = serialize(existing) if existing else {}
    if existing and not reason.strip():
        fail("Alasan perubahan wajib diisi.")
    row = existing or Record(id=kind[:3].upper() + "-" + uuid.uuid4().hex[:10].upper(), kind=kind, created_by=user.email,
                             created_at=now(), workflow=settings(db)["workflows"].get(kind, []))
    if kind == "claims":
        data["name"] = row.id
    row.data = data
    row.natural_key = key
    row.contractor_id, row.site_id = data.get("contractor_id"), data.get("site_id")
    row.modified_at, row.modified_by = now(), user.email
    row.version = row.version + 1 if existing else 1
    row.status = "DRAFT" if row.workflow else "ACTIVE"
    row.stage = 0
    db.add(row)
    db.flush()
    audit(db, user, "UPDATE" if existing else "CREATE", row, before, reason)
    return row

def has_dependents(db, row):
    for other in db.scalars(select(Record).where(Record.id != row.id, Record.status.not_in(INACTIVE))):
        def references(value):
            if isinstance(value, dict):
                return any((key.endswith("_id") and item == row.id) or references(item) for key, item in value.items())
            if isinstance(value, list):
                return any(references(item) for item in value)
            return False
        if references(other.data):
            return True
    return False

def transition(db, user, row, action, comment, version):
    if version != row.version:
        fail("Data telah berubah. Muat ulang sebelum melanjutkan.", 409)
    before = serialize(row)
    next_role = row.workflow[row.stage] if row.stage < len(row.workflow) else None
    approver = user.role == ADMIN or user.role == next_role
    if action == "submit":
        if not can_write(user, row.kind) or row.status not in ("DRAFT", "RETURNED", "REJECTED"):
            fail("Tidak dapat submit transaksi ini.", 403)
        validated = validate(db, user, row.kind, row.data, row.id)
        if row.kind == "reconciliations" and validated["exception"] and not validated["resolution"]:
            fail("Variance melewati toleransi. Isi investigasi dan penyelesaian sebelum submit.")
        row.data = {**validated, **({"name": row.id} if row.kind == "claims" else {})}
        row.status, row.stage = "SUBMITTED", 0
    elif action in ("approve", "reject", "return"):
        if row.status != "SUBMITTED" or not approver:
            fail("Anda bukan approver pada tahap ini.", 403)
        if action != "approve" and not comment.strip():
            fail("Komentar wajib untuk reject/return.")
        if action == "approve":
            current = validate(db, user, row.kind, row.data, row.id)
            if row.kind == "claims" and any(current.get(k) != row.data.get(k) for k in ("rate_id", "gross", "retention", "penalty", "incentive", "net", "evidence")):
                fail("Perhitungan claim berubah. Kembalikan untuk revisi dan submit ulang sebelum approval.", 409)
            row.stage += 1
            if row.stage >= len(row.workflow):
                row.status = "VERIFIED" if row.kind == "production" else "APPROVED"
                row.data = {**row.data, "approved_by": user.email, "approved_at": now().isoformat()}
        else:
            row.status = "REJECTED" if action == "reject" else "RETURNED"
            row.stage = 0
    elif action == "cancel":
        if not can_write(user, row.kind) or row.status in FINAL or row.status == "SUBMITTED" or has_dependents(db, row):
            fail("Transaksi tidak dapat dibatalkan karena status atau referensi aktif.", 409)
        if not comment.strip():
            fail("Alasan pembatalan wajib.")
        row.status = "CANCELLED"
    elif action == "request_reopen":
        if row.status not in ("APPROVED", "VERIFIED") or not can_write(user, row.kind) or not comment.strip():
            fail("Permintaan reopen membutuhkan hak edit, status final, dan alasan.", 403)
        row.data = {**row.data, "reopen_request": {"by": user.email, "reason": comment}}
    elif action == "approve_reopen":
        if user.role not in (ADMIN, "Mine Manager") or not row.data.get("reopen_request"):
            fail("Reopen memerlukan persetujuan Mine Manager.", 403)
        if has_dependents(db, row):
            fail("Reopen ditolak: transaksi telah digunakan oleh proses berikutnya.", 409)
        row.data = {k: v for k, v in row.data.items() if k not in ("reopen_request", "approved_by", "approved_at")}
        row.status, row.stage = "DRAFT", 0
    elif action == "pay":
        if row.kind != "invoices" or row.status != "APPROVED" or user.role not in (ADMIN, "Finance") or not comment.strip():
            fail("Payment hanya oleh Finance untuk invoice approved; isi referensi pembayaran.", 403)
        row.status = "CLOSED"
        row.data = {**row.data, "payment_reference": comment, "paid_at": now().isoformat(), "paid_by": user.email}
    else:
        fail("Aksi tidak dikenal.")
    row.version += 1
    row.modified_at, row.modified_by = now(), user.email
    audit(db, user, action.upper(), row, before, comment)
    return row

def stockpile_balance(db, stockpile_id, exclude=None):
    stockpile = db.get(Record, stockpile_id)
    if not stockpile or stockpile.kind != "stockpiles":
        fail("Stockpile tidak ditemukan.", 404)
    balance = float(stockpile.data.get("opening_balance") or 0)
    for movement in all_rows(db, "stockpile_movements", exclude):
        data = movement.data
        if movement.status not in FINAL or data.get("stockpile_id") != stockpile_id:
            continue
        source_hauling_id = data.get("source_hauling_id")
        if source_hauling_id:
            hauling = db.get(Record, source_hauling_id)
            if not hauling or hauling.kind != "hauling" or hauling.status != "APPROVED":
                continue
        sign = 1 if data.get("direction") == "IN" else -1
        balance += sign * float(data.get("quantity") or 0)
    return round(balance, 2)

def stockpile_snapshot(db, stockpile):
    balance = stockpile_balance(db, stockpile.id)
    capacity = float(stockpile.data.get("capacity") or 0)
    minimum = float(stockpile.data.get("minimum_stock") or 0)
    return {**serialize(stockpile), "book_balance": balance,
            "available_capacity": round(max(0, capacity - balance), 2),
            "capacity_utilization": round(balance / capacity * 100, 2) if capacity else 0,
            "below_minimum": balance < minimum}

def sync_hauling_receipt(db, user, hauling):
    if hauling.kind != "hauling" or hauling.status != "APPROVED":
        return None
    key = "hauling-receipt:" + hauling.id
    receipt = db.scalar(select(Record).where(Record.natural_key == key))
    data = {"date": hauling.data["date"], "site_id": hauling.data["site_id"],
            "stockpile_id": hauling.data["destination_stockpile_id"], "direction": "IN",
            "movement_type": "Hauling Receipt", "quantity": hauling.data["quantity"], "unit": "Ton",
            "reference": hauling.data["transport_reference"],
            "notes": "Penerimaan otomatis dari Coal Hauling " + hauling.id,
            "source_hauling_id": hauling.id, "transport_mode": hauling.data["transport_mode"],
            "distance": hauling.data["distance"], "ton_km": hauling.data.get("ton_km", 0)}
    if receipt:
        before = serialize(receipt)
        receipt.data, receipt.status, receipt.modified_by, receipt.modified_at = data, "APPROVED", user.email, now()
        receipt.version += 1
        audit(db, user, "HAULING_RECEIPT_UPDATED", receipt, before, "Sinkronisasi haul approved")
        return receipt
    receipt = Record(id="STM-" + uuid.uuid4().hex[:10].upper(), kind="stockpile_movements", natural_key=key,
                     contractor_id=hauling.contractor_id, site_id=hauling.site_id, data=data, status="APPROVED", stage=0,
                     workflow=[], version=1, created_by=user.email, created_at=now(), modified_by=user.email, modified_at=now())
    db.add(receipt)
    db.flush()
    audit(db, user, "HAULING_RECEIPT_POSTED", receipt, reason="Penerimaan otomatis dari Coal Hauling approved")
    return receipt