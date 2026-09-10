import hashlib
import hmac
import secrets
from datetime import timedelta
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from .database import SessionLocal, User, AuthSession, now
from .catalog import ADMIN, CONTRACTOR_ROLES, CATALOG

def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return salt + ":" + digest

def verify_password(password, stored):
    salt, expected = stored.split(":")
    actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(expected, actual)

def db_session():
    with SessionLocal() as db:
        yield db

def current_user(request: Request, db=Depends(db_session)):
    token = request.cookies.get("mcms_session", "")
    session = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
    if not session or session.expires_at < now():
        raise HTTPException(401, "Sesi berakhir. Silakan login kembali.")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Akun tidak aktif.")
    # Rolling idle timeout; cookies contain only an opaque random token.
    session.expires_at = now() + timedelta(minutes=30)
    db.commit()
    return user

def visible(user, row):
    if user.role == ADMIN:
        return True
    if user.site_id and row.site_id != user.site_id and not (row.kind == "sites" and row.id == user.site_id):
        return False
    if user.role in CONTRACTOR_ROLES:
        if row.kind in ("sites", "pits", "locations"):
            return True
        if row.kind == "contractors":
            return row.id == user.contractor_id
        return row.contractor_id == user.contractor_id
    return True

def scope_query(user, query, model):
    if user.role == ADMIN:
        return query
    if user.site_id:
        query = query.where((model.site_id == user.site_id) | ((model.kind == "sites") & (model.id == user.site_id)))
    if user.role in CONTRACTOR_ROLES:
        query = query.where((model.contractor_id == user.contractor_id) | ((model.kind == "contractors") & (model.id == user.contractor_id)) | model.kind.in_(["sites", "pits", "locations"]))
    return query

def can_write(user, kind):
    return user.role == ADMIN or user.role in CATALOG[kind]["writers"]

def require_admin(user):
    if user.role != ADMIN:
        raise HTTPException(403, "Hanya System Administrator.")

def public_user(user):
    return {k: getattr(user, k) for k in ("id", "email", "name", "role", "site_id", "contractor_id", "active")}
