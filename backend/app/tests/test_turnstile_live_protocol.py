"""Actual backend -> LAN worker -> synthetic pinned HTTPS device -> readback.

This is protocol simulation, never physical-device acceptance.
"""
import hashlib
from io import BytesIO
import os
from pathlib import Path
import sys
import pytest
from uuid import uuid4
from PIL import Image
sys.path.insert(0, os.environ.get("HIKVISION_CONNECTOR_TEST_DIR", str(Path(__file__).resolve().parents[3]/"connectors/hikvision_attendance")))
from live_worker import Worker
from test_live_device import tls_device as tls_device, MemoryJournal, add_person, policy
from app.tests.test_turnstile_live import live as live, PREFIX
from app.tests.conftest import TestSessionLocal
from app.schemas import AttendanceDevice, Employee
from app.schemas.people.turnstile import GateEmployeeDevice, GatePhotoAsset
from app.schemas.people.turnstile_live import GateLiveJob, GateLiveProfile


class BackendERP:
    def __init__(self, client, worker): self.client = client; self.headers = worker; self.permits = 0
    def claim(self):
        r = self.client.post(PREFIX+"/worker/claim", headers=self.headers); assert r.status_code == 200, r.text
        return r.json()
    def dispatch(self, job, step):
        r = self.client.post(f"{PREFIX}/worker/jobs/{job['job_id']}/dispatch", headers={**self.headers,"X-Turnstile-Lease":job["lease_token"]}, json={"step":step})
        assert r.status_code == 200, r.text
        self.permits += 1
    def photo(self, job):
        r = self.client.get(f"{PREFIX}/worker/jobs/{job['job_id']}/photo", headers={**self.headers,"X-Turnstile-Lease":job["lease_token"]})
        assert r.status_code == 200, r.text
        assert hashlib.sha256(r.content).hexdigest() == job["photo_sha256"]
        return r.content
    def result(self, job, result):
        r = self.client.post(f"{PREFIX}/worker/jobs/{job['job_id']}/result", headers=self.headers, json={"lease_token":job["lease_token"],**result})
        assert r.status_code == 200, r.text
        return r.json()


def configured(live, state, *, writes=True):
    client, person, device_id, auth, _ = live
    with TestSessionLocal() as db:
        db.get(AttendanceDevice, device_id).certificate_sha256=state["pin"]; db.commit()
    config={"enabled":True,"writes_enabled":writes,"allowed_employee_numbers":["LIVE-123"],"face_library_id":"1",
        "access_policy":policy(),"policy_reference":"SYNTHETIC-POLICY-1","handover_reference":"SYNTHETIC-ISOLATED-PILOT-1"}
    r=client.put(f"{PREFIX}/devices/{device_id}",headers=auth,json=config); assert r.status_code==200,r.text
    headers={"X-Turnstile-Worker-Token":r.json()["worker_token"]}
    erp=BackendERP(client,headers)
    worker=Worker(erp,{"device_key":"synthetic-live","hikvision_base_url":state["base_url"],
        "hikvision_cert_sha256":state["pin"],"writes_enabled":writes,"allowed_employee_numbers":["LIVE-123"]},MemoryJournal(),write_approved=writes)
    return client,person,device_id,auth,headers,worker


def upload(client,person,auth,color):
    picture=BytesIO();Image.new("RGB",(32,48),color).save(picture,format="JPEG")
    r=client.post(f"/api/turnstile-access/employees/{person}/photos",headers=auth,files={"file":("synthetic.jpg",picture.getvalue(),"image/jpeg")})
    assert r.status_code==201,r.text
    return r.json()["id"]


def submit(client,person,device,auth,action,**fields):
    r=client.post(f"{PREFIX}/employees/{person}/jobs",headers={**auth,"Idempotency-Key":str(uuid4())},json={
        "expected_employee_no":"LIVE-123","device_id":device,"action":action,**fields})
    assert r.status_code==202,r.text
    return r.json()


def profile(client,person,auth):
    r=client.get(f"{PREFIX}/employees/{person}",headers=auth);assert r.status_code==200,r.text
    return r.json()["profiles"][0]


@pytest.mark.parametrize("double_lock_advertised", [True, False])
def test_complete_physical_protocol_lifecycle_preserves_hr_and_other_profile(live,tls_device,tmp_path,monkeypatch,double_lock_advertised):
    from app.core.config import settings
    monkeypatch.setattr(settings,"TURNSTILE_PHOTOS_DIR",str(tmp_path/"photos"))
    monkeypatch.setattr("live_worker.time.sleep", lambda _: None)
    if not double_lock_advertised:
        tls_device["privilege_capabilities"].pop("doubleLockRight")
    tls_device["delete_status"] = ["idle", "idle", "processing", "success"]
    client,person,device_id,auth,headers,worker=configured(live,tls_device)
    add_person(tls_device,"OTHER","Synthetic unrelated")
    photo=upload(client,person,auth,(130,30,90))
    submit(client,person,device_id,auth,"enroll",reviewed_name="Device Name",photo_asset_id=photo,manual_face_reviewed=True)
    result=worker.once();assert result["state"]=="succeeded",result
    p=profile(client,person,auth);assert p["snapshot"]["full_name"]=="Device Name"
    assert p["snapshot"]["security_capabilities"]["double_lock"] == ("advertised" if double_lock_advertised else "not_advertised")
    assert p["snapshot"]["local_ui_right"] is False
    assert p["snapshot"]["double_lock_right"] is (False if double_lock_advertised else None)
    submit(client,person,device_id,auth,"edit",reviewed_name="Device Edited",expected_profile_hash=p["profile_hash"])
    assert worker.once()["state"]=="succeeded"
    p=profile(client,person,auth)
    photo2=upload(client,person,auth,(10,140,180))
    submit(client,person,device_id,auth,"photo",photo_asset_id=photo2,manual_face_reviewed=True,expected_profile_hash=p["profile_hash"])
    assert worker.once()["state"]=="succeeded"
    p=profile(client,person,auth);assert p["snapshot"]["full_name"]=="Device Edited"
    submit(client,person,device_id,auth,"revoke",expected_profile_hash=p["profile_hash"])
    assert worker.once()["state"]=="succeeded"
    p=profile(client,person,auth);assert p["snapshot"]["user_type"]=="blackList" and "LIVE-123" in tls_device["photos"]
    submit(client,person,device_id,auth,"restore",expected_profile_hash=p["profile_hash"])
    assert worker.once()["state"]=="succeeded"
    p=profile(client,person,auth);assert p["snapshot"]["user_type"]=="normal"
    submit(client,person,device_id,auth,"revoke",expected_profile_hash=p["profile_hash"])
    assert worker.once()["state"]=="succeeded"
    p=profile(client,person,auth)
    submit(client,person,device_id,auth,"delete",delete_credentials_confirmed=True,expected_profile_hash=p["profile_hash"])
    assert worker.once()["state"]=="succeeded"
    assert "LIVE-123" not in tls_device["persons"] and "OTHER" in tls_device["persons"]
    with TestSessionLocal() as db:
        assert db.get(Employee,person).full_name=="Synthetic Person" and db.get(Employee,person).status=="active"
        assert db.query(GatePhotoAsset).count()==2 and db.query(GateEmployeeDevice).count()==1
        assert db.query(GateLiveProfile).one().snapshot["present"] is False
        assert len(db.query(GateLiveJob).all())==7


def test_real_observation_adoption_and_baseline_drift(live,tls_device):
    client,person,device_id,auth,headers,worker=configured(live,tls_device)
    add_person(tls_device,"LIVE-123")
    submit(client,person,device_id,auth,"observe")
    observed=worker.once();assert observed["state"]=="succeeded"
    r=client.post(f"{PREFIX}/employees/{person}/adopt",headers=auth,json={"expected_employee_no":"LIVE-123",
        "observation_job_id":observed["id"],"expected_profile_hash":observed["profile_hash"],"identity_reviewed":True})
    assert r.status_code==200,r.text
    p=profile(client,person,auth);tls_device["persons"]["LIVE-123"]["localUIRight"]=True
    submit(client,person,device_id,auth,"edit",reviewed_name="Changed",expected_profile_hash=p["profile_hash"])
    assert worker.once()["state"]=="conflict" and not tls_device["writes"]
    submit(client,person,device_id,auth,"observe");new=worker.once()
    r=client.post(f"{PREFIX}/employees/{person}/adopt",headers=auth,json={"expected_employee_no":"LIVE-123",
        "observation_job_id":new["id"],"expected_profile_hash":new["profile_hash"],"identity_reviewed":True})
    assert r.status_code==200,r.text
    assert profile(client,person,auth)["snapshot"]["other_fields_hash"]!=p["snapshot"]["other_fields_hash"]


def test_unknown_write_blocks_device_until_quiescent_read_only_resolution(live,tls_device):
    client,person,device_id,auth,headers,worker=configured(live,tls_device)
    add_person(tls_device,"LIVE-123")
    submit(client,person,device_id,auth,"observe");observed=worker.once()
    client.post(f"{PREFIX}/employees/{person}/adopt",headers=auth,json={"expected_employee_no":"LIVE-123",
        "observation_job_id":observed["id"],"expected_profile_hash":observed["profile_hash"],"identity_reviewed":True})
    p=profile(client,person,auth)
    submit(client,person,device_id,auth,"edit",reviewed_name="Changed once",expected_profile_hash=p["profile_hash"])
    tls_device["drop_after"]="/ISAPI/AccessControl/UserInfo/Modify"
    failed=worker.once();assert failed["state"]=="uncertain" and len(tls_device["writes"])==1
    r=client.post(f"{PREFIX}/employees/{person}/jobs",headers={**auth,"Idempotency-Key":"must-block"},json={
        "expected_employee_no":"LIVE-123","device_id":device_id,"action":"revoke","expected_profile_hash":p["profile_hash"]})
    assert r.status_code==409
    submit(client,person,device_id,auth,"observe");fresh=worker.once();assert fresh["state"]=="succeeded"
    r=client.post(f"{PREFIX}/jobs/{failed['id']}/resolve",headers=auth,json={"worker_stopped_reference":"SYNTHETIC-WORKER-QUIESCENT",
        "observation_job_id":fresh["id"]})
    assert r.status_code==200 and r.json()["state"]=="conflict",r.text
    assert len(tls_device["writes"])==1 and profile(client,person,auth)["snapshot"]["full_name"]=="Changed once"
