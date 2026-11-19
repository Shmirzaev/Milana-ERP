"""Loopback-only synthetic turnstile HTTP verification. Run only in owned QA runtime.

Requires explicit TURNSTILE_VERIFY_SYNTHETIC=1, private development settings,
and PostgreSQL database milana_devqa or the exact dedicated publication DB.
Fixtures and evidence are retained.
Never prints credentials, environment, image bytes, or response bodies.
"""
from collections import Counter
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import struct
import zlib
from uuid import uuid4

import httpx
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.libs.enums.turnstile import GateMode
from app.schemas import AttendanceDevice, AttendanceEvent, AttendancePerson, Employee, Role, User, AuditLog, IdempotencyRecord
from app.schemas.people.turnstile import GatePhotoAsset, GateOperation, GateSimulatorDevice, GateSimulatorPerson, GateEmployeeDevice
from app.schemas.people.turnstile_persistence import set_simulator_device

BASE = "http://127.0.0.1:8000"
PREFIX = "/api/turnstile-access"

def check(value, label):
    if not value:
        raise AssertionError(label)

def fingerprint(rows):
    data = [{c.name: str(getattr(row, c.name)) for c in row.__table__.columns} for row in rows]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

def image_bytes(fmt, *, orientation=None):
    image = Image.new("RGB", (12, 8), (50, 120, 190))
    out = BytesIO()
    if orientation is not None:
        exif = image.getexif()
        exif[274] = orientation
        exif[270] = "private metadata"
        image.save(out, format=fmt, exif=exif)
    else:
        image.save(out, format=fmt)
    return out.getvalue()

def huge_png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 100000, 100000, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00")) + chunk(b"IEND", b"")

def main():
    url = make_url(settings.DATABASE_URL)
    check(os.environ.get("TURNSTILE_VERIFY_SYNTHETIC") == "1", "synthetic opt-in required")
    check(url.get_backend_name() == "postgresql" and (url.database == "milana_devqa" or url.database == "turnstile_verify_publish_20261103"), "dedicated QA database required")
    check(not settings.strict_security_required and settings.TURNSTILE_PROVISIONING_MODE == GateMode.SIMULATOR, "private simulator environment required")
    prefix = "th" + uuid4().hex[:14]
    password = secrets.token_urlsafe(24)
    credentials = {}
    with SessionLocal() as db:
        roles = {}
        for label, permissions in (("hr", ["hr.employees"]), ("provision", ["attendance.provision"]), ("both", ["attendance.provision", "hr.employees"])):
            role = Role(name=prefix + label, permissions=permissions)
            email = prefix + label + "@example.com"
            user = User(name="Synthetic", email=email, password_hash=hash_password(password), role=role, factory_code="MIL", extra_permissions=[], is_active=True)
            db.add(user)
            credentials[label] = email
            roles[label] = user
        employee = Employee(factory_code="MIL", employee_no=prefix, full_name="Synthetic Employee", status="active", hr_profile_json={})
        foreign = Employee(factory_code="BET", employee_no=prefix, full_name="Synthetic Foreign", status="active", hr_profile_json={})
        devices = [AttendanceDevice(factory_code="MIL", device_key=prefix + str(i), name="Synthetic gate", sync_enabled=True, read_only=True) for i in range(4)]
        db.add_all([employee, foreign, *devices])
        db.flush()
        configs = [GateSimulatorDevice(device_id=d.id, factory_code="MIL", mode=GateMode.SIMULATOR, online=i != 3) for i, d in enumerate(devices)]
        db.add_all(configs)
        foreign_photo = GatePhotoAsset(employee_id=foreign.id, factory_code="BET", created_by=roles["both"].id, stored_name=uuid4().hex + ".jpg", sha256="a"*64, width=1, height=1, content_type="image/jpeg")
        db.add(foreign_photo)
        db.flush()
        eid, fid, foreign_asset = employee.id, foreign.id, foreign_photo.id
        device_ids = [d.id for d in devices]
        actor_id = roles["both"].id
        before = {
            "employee": fingerprint([employee, foreign]),
            "devices": fingerprint(devices),
            "mirror": fingerprint(db.scalars(select(AttendancePerson).where(AttendancePerson.device_id.in_(device_ids)).order_by(AttendancePerson.id)).all()),
            "events": fingerprint(db.scalars(select(AttendanceEvent).where(AttendanceEvent.device_id.in_(device_ids)).order_by(AttendanceEvent.id)).all()),
        }
        db.commit()

    def req(client, method, path, expected, **kwargs):
        try:
            response = client.request(method, PREFIX + path, timeout=15.0, **kwargs)
        except httpx.TransportError as exc:
            raise RuntimeError("HOLD: request outcome unknown; do not retry") from exc
        check(response.status_code == expected, "HTTP status mismatch: expected " + str(expected) + " got " + str(response.status_code))
        return response

    clients = {k: httpx.Client(base_url=BASE, timeout=15.0, trust_env=False, follow_redirects=False) for k in credentials}
    anonymous = httpx.Client(base_url=BASE, timeout=15.0, trust_env=False, follow_redirects=False)
    try:
        for label, client in clients.items():
            try:
                response = client.post("/api/auth/login-json", json={"email": credentials[label], "password": password, "factory_code": "MIL"}, timeout=15.0)
            except httpx.TransportError as exc:
                raise RuntimeError("HOLD: login outcome unknown; do not retry") from exc
            check(response.status_code == 200 and bool(client.cookies), "cookie login")
        for method, path, kwargs in [
            ("GET", f"/employees/{eid}", {}),
            ("GET", "/operations/999999999", {}),
            ("GET", "/photos/999999999", {}),
            ("POST", f"/employees/{eid}/photos", {"files":{"file":("a.png", image_bytes("PNG"), "image/png")}}),
            ("POST", f"/employees/{eid}/enroll", {"json":{}}),
            ("POST", "/operations/999999999/simulate", {}),
            ("POST", "/operations/999999999/simulator-reconnect", {}),
        ]:
            req(anonymous, method, path, 401, **kwargs)
        for label in ("hr", "provision"):
            req(clients[label], "GET", f"/employees/{eid}", 403)
            req(clients[label], "GET", "/photos/999999999", 403)
            req(clients[label], "POST", f"/employees/{eid}/enroll", 403, json={"device_ids":[device_ids[0]], "photo_asset_id":999999999, "manual_face_reviewed":True, "expected_employee_no":prefix}, headers={"Idempotency-Key":prefix + label})
            req(clients[label], "POST", "/operations/999999999/simulate", 403)
            req(clients[label], "POST", "/operations/999999999/simulator-reconnect", 403)
            req(clients[label], "POST", f"/employees/{eid}/photos", 403, files={"file":("a.png", image_bytes("PNG"), "image/png")})
        with SessionLocal() as db:
            check(db.scalar(select(func.count()).select_from(GatePhotoAsset).where(GatePhotoAsset.employee_id == eid)) == 0, "unauthorized uploads wrote assets")
        client = clients["both"]
        req(client, "GET", f"/employees/{fid}", 404)
        req(client, "GET", f"/photos/{foreign_asset}", 404)
        req(client, "POST", f"/employees/{fid}/photos", 404, files={"file":("a.png", image_bytes("PNG"), "image/png")})
        for content, name in [(b"broken", "a.png"), (huge_png(), "a.png"), (b"x" * (settings.TURNSTILE_PHOTO_MAX_BYTES + 1), "a.png")]:
            req(client, "POST", f"/employees/{eid}/photos", 400, files={"file":(name, content, "image/png")})
        png = req(client, "POST", f"/employees/{eid}/photos", 201, files={"file":("a.png", image_bytes("PNG"), "image/png")}).json()
        jpeg = req(client, "POST", f"/employees/{eid}/photos", 201, files={"file":("a.jpg", image_bytes("JPEG", orientation=6), "image/jpeg")}).json()
        photo = req(client, "GET", f"/photos/{jpeg['id']}", 200)
        check("no-store" in photo.headers.get("cache-control", ""), "photo no-store")
        with Image.open(BytesIO(photo.content)) as normalized:
            check(normalized.size == (8, 12) and not normalized.getexif(), "EXIF orientation or metadata stripping")
        with SessionLocal() as db:
            asset = db.get(GatePhotoAsset, jpeg["id"])
            stored = Path(settings.TURNSTILE_PHOTOS_DIR).resolve() / asset.stored_name
            check(stored.is_file() and stat.S_IMODE(stored.stat().st_mode) == 0o600, "private photo file permissions")
            check(hashlib.sha256(photo.content).hexdigest() == asset.sha256, "photo digest")
        payload = {"device_ids": device_ids, "photo_asset_id": png["id"], "manual_face_reviewed": True, "expected_employee_no": prefix}
        with SessionLocal() as db:
            changed_employee = db.get(Employee, eid)
            changed_employee.employee_no = prefix + "changed"
            db.commit()
        req(client, "POST", f"/employees/{eid}/enroll", 409, json=payload, headers={"Idempotency-Key":prefix + "stale"})
        with SessionLocal() as db:
            check(db.scalar(select(func.count()).select_from(GateOperation).where(GateOperation.employee_id == eid)) == 0, "stale employee number created an operation")
            changed_employee = db.get(Employee, eid)
            changed_employee.employee_no = prefix
            db.commit()
            before["employee"] = fingerprint(db.scalars(select(Employee).where(Employee.id.in_([eid, fid])).order_by(Employee.id)).all())
        req(client, "POST", f"/employees/{eid}/enroll", 400, json=payload)
        req(client, "POST", f"/employees/{eid}/enroll", 422, json={**payload, "device_ids":[device_ids[0], device_ids[0]]}, headers={"Idempotency-Key":prefix + "bad"})
        first = req(client, "POST", f"/employees/{eid}/enroll", 202, json=payload, headers={"Idempotency-Key":prefix + "ok"}).json()
        check(Counter(t["state"] for t in first["targets"]) == {"queued":4}, "queued targets")
        replay = req(client, "POST", f"/employees/{eid}/enroll", 202, json=payload, headers={"Idempotency-Key":prefix + "ok"}).json()
        check(first["id"] == replay["id"], "replay operation identity")
        req(client, "POST", f"/employees/{eid}/enroll", 409, json={**payload, "reviewed_name":"Changed"}, headers={"Idempotency-Key":prefix + "ok"})
        simulated = req(client, "POST", f"/operations/{first['id']}/simulate", 200).json()
        check(Counter(t["state"] for t in simulated["targets"]) == {"succeeded":3, "waiting":1}, "partial simulation")
        recovered = req(client, "POST", f"/operations/{first['id']}/simulator-reconnect", 200).json()
        check(Counter(t["state"] for t in recovered["targets"]) == {"succeeded":4}, "reconnect")
        with SessionLocal() as db:
            check(db.scalar(select(func.count()).select_from(GateOperation).where(GateOperation.employee_id == eid)) == 1, "single durable operation")
            check(db.scalar(select(func.count()).select_from(IdempotencyRecord).where(IdempotencyRecord.user_id == actor_id, IdempotencyRecord.key == prefix + "ok")) == 1, "idempotency record")
            check(db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_type == "gate_operation", AuditLog.entity_id == first["id"])) == 1, "audit record")
            people = db.scalars(select(GateSimulatorPerson).join(GateEmployeeDevice, GateSimulatorPerson.binding_id == GateEmployeeDevice.id).where(GateEmployeeDevice.employee_id == eid)).all()
            check(len(people) == 4 and all(p.write_count == 1 for p in people), "simulator write counts")
            after = {
                "employee": fingerprint(db.scalars(select(Employee).where(Employee.id.in_([eid, fid])).order_by(Employee.id)).all()),
                "devices": fingerprint(db.scalars(select(AttendanceDevice).where(AttendanceDevice.id.in_(device_ids)).order_by(AttendanceDevice.id)).all()),
                "mirror": fingerprint(db.scalars(select(AttendancePerson).where(AttendancePerson.device_id.in_(device_ids)).order_by(AttendancePerson.id)).all()),
                "events": fingerprint(db.scalars(select(AttendanceEvent).where(AttendanceEvent.device_id.in_(device_ids)).order_by(AttendanceEvent.id)).all()),
            }
            check(before == after, "HR, mirror, event or ingestion device changed")
        with SessionLocal() as db:
            for device_id in device_ids:
                set_simulator_device(db, device_id=device_id, factory_code="MIL", online=False, mode=GateMode.DISABLED)
            db.commit()
        print(json.dumps({"result":"PASS", "roles":3, "targets":4, "photos":2, "operations":1, "simulator_writes":4, "integrity":"unchanged"}))
    finally:
        anonymous.close()
        for client in clients.values():
            client.close()

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"result":"HOLD", "reason":str(exc) if isinstance(exc, (AssertionError, RuntimeError)) else type(exc).__name__}))
        raise SystemExit(1)
