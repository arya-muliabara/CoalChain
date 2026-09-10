import os
import tempfile
import uuid
from datetime import date
from pathlib import Path
import pytest

TEST_DIR = Path(tempfile.mkdtemp(prefix="mcms-test-"))
os.environ["DATABASE_URL"] = "sqlite:///" + (TEST_DIR / "test.db").as_posix()
os.environ["MCMS_STORAGE"] = str(TEST_DIR / "documents")
os.environ["MCMS_ADMIN_PASSWORD"] = "CoalChain-Test-2026!"
os.environ["MCMS_DEMO_PASSWORD"] = "CoalChain-Test-2026!"
os.environ["MCMS_DEMO"] = "true"
os.environ["MCMS_WORKER_SECRET"] = "test-worker-secret"
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, Record, Config
from app.catalog import CATALOG
from sqlalchemy import select

HEADERS = {"X-MCMS-Request": "1"}
PASSWORD = "CoalChain-Test-2026!"

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"email":"admin@coalchain.local","password":PASSWORD}, headers=HEADERS)
        assert r.status_code == 200
        yield c

def rows(client, kind):
    return client.get("/api/records/"+kind+"?limit=100").json()["items"]

def payload(row):
    return {f["key"]: row.get(f["key"]) for f in CATALOG[row["kind"]]["fields"]}

def create(client, kind, data):
    response = client.post("/api/records/"+kind, json={"data":data}, headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()

def action(client, row, action, comment="Test evidence"):
    return client.post("/api/record/"+row["id"]+"/action", json={"action":action,"version":row["version"],"comment":comment}, headers=HEADERS)

def approve(client, row):
    response = action(client, row, "submit")
    assert response.status_code == 200, response.text
    row = response.json()
    while row["status"] == "SUBMITTED":
        response = action(client, row, "approve")
        assert response.status_code == 200, response.text
        row = response.json()
    return row

def sample(client, kind, status=None):
    return next(r for r in rows(client,kind) if status is None or r["status"] == status)

def new_production(client, quantity=1000, day=20):
    prod = sample(client,"production","VERIFIED")
    data = payload(prod)
    data.update(date=date.today().strftime("%Y-%m")+f"-{day:02d}",quantity=quantity,block="TEST-"+uuid.uuid4().hex[:5])
    # Different pit/block alone must not bypass the DPR equipment+shift identity.
    data["shift"] = "Night"
    data["activity"], data["material"], data["unit"] = "OB Removal", "Overburden", "BCM"
    return data

def test_authentication_and_csrf(client):
    other=TestClient(app)
    assert other.get("/api/records/contracts").status_code == 401
    assert client.post("/api/records/production",json={"data":{}}).status_code == 403
    assert other.post("/api/auth/login",json={"email":"admin@coalchain.local","password":"incorrect"},headers=HEADERS).status_code==401

def test_dashboard_and_catalog(client):
    data=client.get("/api/dashboard").json()
    assert data["coal"] > 0 and data["ob"] > 0 and data["pa"] <= 100
    assert len(client.get("/api/catalog").json()["modules"]) >= 20
    assert client.get("/api/dashboard?period=bad").status_code == 422

def test_duplicate_production_database_identity(client):
    data=payload(sample(client,"production"))
    r=client.post("/api/records/production",json={"data":data},headers=HEADERS)
    assert r.status_code==409 and "duplikat" in r.text

def test_invalid_equipment_and_hours(client):
    data=new_production(client)
    data["equipment_id"]="NOT-EXISTS"
    assert client.post("/api/records/production",json={"data":data},headers=HEADERS).status_code==404
    data=new_production(client)
    data["working"]=25
    assert client.post("/api/records/production",json={"data":data},headers=HEADERS).status_code==422

def test_equipment_contractor_mismatch(client):
    data=new_production(client)
    equipment=next(r for r in rows(client,"equipment") if r["contractor_id"] != data["contractor_id"])
    data["equipment_id"]=equipment["id"]
    r=client.post("/api/records/production",json={"data":data},headers=HEADERS)
    assert r.status_code==422

def test_final_data_immutable_and_stale_version(client):
    row=sample(client,"production","VERIFIED")
    r=client.put("/api/record/"+row["id"],json={"data":payload(row),"version":row["version"],"reason":"Try modifying final"},headers=HEADERS)
    assert r.status_code==409
    draft=create(client,"production",new_production(client,day=21))
    r=client.put("/api/record/"+draft["id"],json={"data":payload(draft),"version":999,"reason":"Stale"},headers=HEADERS)
    assert r.status_code==409

def test_contractor_scope_and_function_access(client):
    other=TestClient(app)
    assert other.post("/api/auth/login",json={"email":"contractor.user@coalchain.local","password":PASSWORD},headers=HEADERS).status_code==200
    me=other.get("/api/auth/me").json()
    mine=rows(other,"production")
    assert mine and all(r["contractor_id"]==me["contractor_id"] for r in mine)
    foreign=next(r for r in rows(client,"production") if r["contractor_id"]!=me["contractor_id"])
    assert other.get("/api/record/"+foreign["id"]).status_code==404
    assert other.post("/api/records/contracts",json={"data":{}},headers=HEADERS).status_code==403
    assert other.get("/api/users").status_code==403
    assert other.get("/api/settings").status_code==403
    assert foreign["id"] not in other.get("/api/export/production").text

def test_wrong_approver(client):
    other=TestClient(app)
    other.post("/api/auth/login",json={"email":"contractor.user@coalchain.local","password":PASSWORD},headers=HEADERS)
    me=other.get("/api/auth/me").json()
    row=next(r for r in rows(client,"production") if r["contractor_id"]==me["contractor_id"])
    data=payload(row)
    data.update(date=date.today().strftime("%Y-%m")+"-22",shift="Night")
    draft=create(other,"production",data)
    submitted=action(other,draft,"submit").json()
    assert action(other,submitted,"approve").status_code==403

def test_idempotent_retry_and_payload_conflict(client):
    data=new_production(client,day=23)
    key=uuid.uuid4().hex
    body={"data":data,"request_id":key}
    first=client.post("/api/records/production",json=body,headers=HEADERS)
    second=client.post("/api/records/production",json=body,headers=HEADERS)
    assert first.status_code==second.status_code==201
    assert first.json()["id"]==second.json()["id"]
    body["data"]={**data,"quantity":333}
    assert client.post("/api/records/production",json=body,headers=HEADERS).status_code==409

def test_invoice_cannot_exceed_approved_claim(client):
    invoice=sample(client,"invoices")
    data=payload(invoice)
    data["name"]="OVER-"+uuid.uuid4().hex[:6]
    data["amount"]=1
    response=client.post("/api/records/invoices",json={"data":data},headers=HEADERS)
    assert response.status_code==422 and "melebihi" in response.text

def test_unapproved_claim_not_invoiceable(client):
    claim=sample(client,"claims","DRAFT")
    invoice=payload(sample(client,"invoices"))
    invoice.update(claim_id=claim["id"],contractor_id=claim["contractor_id"],amount=1,name="UNAPPROVED")
    r=client.post("/api/records/invoices",json={"data":invoice},headers=HEADERS)
    assert r.status_code==422 and "APPROVED" in r.text

def test_reopen_blocked_by_downstream(client):
    survey=sample(client,"surveys","APPROVED")
    request=action(client,survey,"request_reopen").json()
    r=action(client,request,"approve_reopen")
    assert r.status_code==409 and "proses berikutnya" in r.text

def test_full_production_to_payment_and_duplicate_claim(client):
    data=new_production(client,day=24)
    prod=approve(client,create(client,"production",data))
    assert prod["status"]=="VERIFIED"
    common={"site_id":prod["site_id"],"contractor_id":prod["contractor_id"]}
    survey_data={**common,"date":prod["date"],"period":prod["date"][:7],"pit_id":prod["pit_id"],"block":prod["block"],"activity":prod["activity"],"material":prod["material"],"beginning":10000,"ending":9020,"quantity":980,"unit":"BCM"}
    survey=approve(client,create(client,"surveys",survey_data))
    rec=approve(client,create(client,"reconciliations",{**common,"production_id":prod["id"],"survey_id":survey["id"],"owner_quantity":1000,"approved_quantity":980,"resolution":"Survey comparison validated"}))
    contract=next(r for r in rows(client,"contracts") if r["contractor_id"]==prod["contractor_id"])
    claim_data={**common,"contract_id":contract["id"],"period":prod["date"][:7],"reconciliation_id":rec["id"],"deduction":0}
    claim=approve(client,create(client,"claims",claim_data))
    assert claim["quantity"]==980 and claim["rate"]==32000
    assert claim["gross"]==31360000 and claim["net"]==29792000
    duplicate=client.post("/api/records/claims",json={"data":claim_data},headers=HEADERS)
    assert duplicate.status_code==422
    invoice=approve(client,create(client,"invoices",{**common,"name":"INV-E2E-"+uuid.uuid4().hex[:6],"claim_id":claim["id"],"date":prod["date"],"due":prod["date"],"amount":claim["net"]}))
    paid=action(client,invoice,"pay","BANK-REFERENCE-123")
    assert paid.status_code==200 and paid.json()["status"]=="CLOSED"
    assert paid.json()["payment_reference"]=="BANK-REFERENCE-123"
    trail=client.get("/api/record/"+invoice["id"]).json()["audit"]
    assert trail[0]["action"]=="PAY" and trail[0]["before"]["status"]=="APPROVED"
    # Rate IDs appear in computed data and must prevent reopening a rate already billed.
    rate=client.get("/api/record/"+claim["rate_id"]).json()["record"]
    requested=action(client,rate,"request_reopen").json()
    assert action(client,requested,"approve_reopen").status_code==409

def test_variance_requires_resolution_and_survey_allocation_limit(client):
    prod=approve(client,create(client,"production",new_production(client,day=25)))
    common={"site_id":prod["site_id"],"contractor_id":prod["contractor_id"]}
    survey=approve(client,create(client,"surveys",{**common,"date":prod["date"],"period":prod["date"][:7],"pit_id":prod["pit_id"],"block":prod["block"],"activity":prod["activity"],"material":prod["material"],"beginning":10000,"ending":9100,"quantity":900,"unit":"BCM"}))
    data={**common,"production_id":prod["id"],"survey_id":survey["id"],"owner_quantity":1000,"approved_quantity":901}
    assert client.post("/api/records/reconciliations",json={"data":data},headers=HEADERS).status_code==422
    data["approved_quantity"]=900
    rec=create(client,"reconciliations",data)
    assert rec["exception"] is True and rec["variance"] == -10
    assert action(client,rec,"submit").status_code==422

def test_import_preview_errors_and_atomic_confirmation(client):
    assert client.get("/api/import/fuel/template").status_code==200
    file=("bad.csv",b"date,liter\nnot-a-date,-5\n","text/csv")
    preview=client.post("/api/import/fuel/preview",files={"file":file},headers=HEADERS).json()
    assert preview["errors"]
    before=client.get("/api/records/fuel").json()["total"]
    r=client.post("/api/import/confirm/"+preview["batch_id"],headers=HEADERS)
    assert r.status_code==422
    assert client.get("/api/records/fuel").json()["total"]==before

def test_successful_csv_import_and_replay(client):
    ct=sample(client,"contractors")
    content=f"date,shift,site_id,contractor_id,position,planned,actual,hours\n{date.today()},Night,{ct['site_id']},{ct['id']},Import crew,10,9,90\n"
    response=client.post("/api/import/manpower/preview",files={"file":("crew.csv",content.encode(),"text/csv")},headers=HEADERS)
    assert response.status_code==200, response.text
    batch=response.json()
    assert not batch["errors"]
    assert client.post("/api/import/confirm/"+batch["batch_id"],headers=HEADERS).json()["posted"]==1
    assert client.post("/api/import/confirm/"+batch["batch_id"],headers=HEADERS).status_code==409

def test_document_upload_download_access(client):
    draft=create(client,"production",new_production(client,day=26))
    r=client.post("/api/record/"+draft["id"]+"/documents",files={"file":("evidence.txt",b"Survey evidence","text/plain")},headers=HEADERS)
    assert r.status_code==200, r.text
    doc=r.json()
    assert client.get("/api/documents/"+doc["id"]).content==b"Survey evidence"
    assert TestClient(app).get("/api/documents/"+doc["id"]).status_code==401
    final=approve(client,draft)
    assert client.post("/api/record/"+final["id"]+"/documents",files={"file":("late.txt",b"late","text/plain")},headers=HEADERS).status_code==403

def test_settings_validation_and_worker_auth(client):
    cfg=client.get("/api/settings").json()
    cfg["weights"]["production"]=99
    assert client.put("/api/settings",json=cfg,headers=HEADERS).status_code==422
    assert client.post("/api/internal/refresh-alerts").status_code==401
    r=client.post("/api/internal/refresh-alerts",headers={"Authorization":"Bearer test-worker-secret"})
    assert r.status_code==200 and "count" in r.json()

def test_equipment_historical_ownership_cannot_change(client):
    eq=sample(client,"equipment")
    # Locate an equipment already referenced by verified production.
    prod=sample(client,"production","VERIFIED")
    eq=client.get("/api/record/"+prod["equipment_id"]).json()["record"]
    data=payload(eq)
    data["contractor_id"]=next(r["id"] for r in rows(client,"contractors") if r["id"]!=eq["contractor_id"])
    r=client.put("/api/record/"+eq["id"],json={"data":data,"version":eq["version"],"reason":"Ownership transfer"},headers=HEADERS)
    assert r.status_code==409

