"""Synthetic HTTPS protocol tests. These never contact factory devices."""
import hashlib
import json
import ssl
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from urllib.parse import urlparse
import pytest
from live_device import LiveDevice, DeviceRefusal
from live_worker import Worker, ProtectedJournal


@pytest.fixture
def tls_device(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from PIL import Image
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Terminal")])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc)+timedelta(days=1)).sign(key, hashes.SHA256()))
    cert_path = tmp_path/"server.pem"; key_path = tmp_path/"server.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    image = BytesIO(); Image.new("RGB", (30, 40), (120, 80, 50)).save(image, format="JPEG")
    state = {"persons": {}, "photos": {}, "requests": [], "writes": [], "redirect": None,
        "reject": None, "drop_after": None, "capacity": 1500, "recompress": False, "digest_challenges": 0,
        "count_response": None, "record_flags": {}, "delete_status": "success", "residual_credentials": False,
        "card_residual": 0, "fp_residual": 0,
        "privilege_capabilities": {"employeeNo": {"@min": 1, "@max": 32},
            "userType": {"@opt": "normal,visitor,blackList"},
            "UserInfoSearchCond": {"isSupportNumOfFace": True, "isSupportNumOfCard": True, "isSupportNumOfFP": True},
            "Valid": {"enable": "true,false"}, "RightPlan": {"maxSize": 4},
            "localUIRight": "true,false", "doubleLockRight": "true,false"},
        "http_error": None, "delete_error": None, "invalid_identity": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def respond(self, value, status=200, content_type="application/json"):
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status); self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_GET(self): self.handle_request()
        def do_POST(self): self.handle_request()
        def do_PUT(self): self.handle_request()

        def handle_request(self):
            size = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(size)
            if not self.headers.get("Authorization", "").startswith("Digest "):
                state["digest_challenges"] += 1
                self.send_response(401); self.send_header("WWW-Authenticate", 'Digest realm="synthetic", nonce="fixed-local-test-nonce", algorithm=MD5, qop="auth"')
                self.send_header("Content-Length", "0"); self.end_headers(); return
            path = urlparse(self.path).path
            state["requests"].append((self.command, path))
            if state["http_error"]:
                return self.respond({"statusCode":6,"statusString":"Invalid Content"},state["http_error"])
            if state["redirect"]:
                self.send_response(302); self.send_header("Location", state["redirect"])
                self.send_header("Content-Length", "0"); self.end_headers(); return
            if path.endswith("/capabilities"):
                if "UserInfo" in path: return self.respond({"UserInfo": state["privilege_capabilities"]})
                if "FDLib" in path:
                    return self.respond({"FDRecordDataMaxNum": state["capacity"], "isSuportFDSearch": True})
                return self.respond({"AccessControl": {"isSupportUserInfo": True, "isSupportFDLib": True, "isSupportUserInfoDetailDelete": True}})
            if path.startswith("/LOCALS/pic/enrlFace/"):
                return self.respond(state["photos"][path.rsplit("/", 1)[-1]], content_type="image/jpeg")
            if path.endswith("/UserInfo/Search"):
                if state["invalid_identity"]:
                    return self.respond({"statusCode": 6, "subStatusCode": "badJsonContent",
                        "errorCode": 1610612759, "errorMsg": "employeeNo"}, 400)
                number = json.loads(body)["UserInfoSearchCond"]["EmployeeNoList"][0]["employeeNo"]
                person = state["persons"].get(number)
                return self.respond({"UserInfoSearch": {"totalMatches": int(person is not None), "numOfMatches": int(person is not None),
                    "responseStatusStrg": "OK" if person else "NO MATCH", "UserInfo": [person] if person else []}})
            if path.endswith("/FDSearch"):
                payload = json.loads(body)
                assert "FDSearchDescription" not in payload
                number = payload.get("FPID")
                found = number in state["photos"]
                return self.respond({"totalMatches": int(found), "numOfMatches": int(found), "responseStatusStrg": "OK" if found else "NO MATCH",
                    "MatchList": [{"FPID": number, "faceURL": state["base_url"]+"/LOCALS/pic/enrlFace/"+number}] if found else []})
            if path.endswith("/CardInfo/Search"):
                number = json.loads(body)["CardInfoSearchCond"]["EmployeeNoList"][0]["employeeNo"]
                count = state["card_residual"] if number not in state["persons"] else state["persons"][number]["numOfCard"]
                return self.respond({"CardInfoSearch": {"totalMatches": count, "responseStatusStrg": "OK" if count else "NO MATCH",
                    "CardInfo": [{"employeeNo": number}] if count else []}})
            if path.endswith("/FingerPrintUpload"):
                number = json.loads(body)["FingerPrintCond"]["employeeNo"]
                count = state["fp_residual"] if number not in state["persons"] else state["persons"][number]["numOfFP"]
                return self.respond({"FingerPrintInfo": {"status": "OK" if count else "NoFP", "FingerPrintList": [{}]*count}})
            if path.endswith("/DeleteProcess"):
                if state["delete_error"] is not None:
                    return self.respond(state["delete_error"], 404)
                status = state["delete_status"]
                if isinstance(status, list):
                    status = status.pop(0) if len(status) > 1 else status[0]
                if status == "idle":
                    return self.respond({"statusCode": 4, "subStatusCode": "taskNotExist",
                        "errorCode": 1073746095, "errorMsg": "taskNotExist"}, 404)
                return self.respond({"UserInfoDetailDeleteProcess": {"status": status}})
            if path.endswith("/FDLib/Count"):
                return self.respond(state["count_response"] if state["count_response"] is not None else {
                    "statusCode": 1, "statusString": "OK", "FDRecordDataInfo": [
                        {"FDID": "1", "faceLibType": "blackFD", "recordDataNumber": len(state["photos"])},
                        {"FDID": "2", "faceLibType": "infraredFD", "recordDataNumber": 0}]})
            state["writes"].append((self.command, path))
            if state["reject"] == path:
                return self.respond({"statusCode": 4, "statusString": "Invalid Operation"})
            if path.endswith("/UserInfo/Record"):
                person = json.loads(body)["UserInfo"]; number = person["employeeNo"]
                if number in state["persons"]: return self.respond({"statusCode": 4, "statusString": "Occupied"})
                state["persons"][number] = {**person, "numOfFace": 0, "numOfCard": 0, "numOfFP": 0, **state["record_flags"]}
            elif path.endswith("/UserInfo/Modify"):
                change = json.loads(body)["UserInfo"]; state["persons"][change["employeeNo"]].update(change)
            elif path.endswith("/FaceDataRecord") or path.endswith("/FDSetUp"):
                boundary = self.headers["Content-Type"].split("boundary=", 1)[1].encode()
                parts = body.split(b"--"+boundary)
                metadata = json.loads(parts[1].split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n"))
                photo = parts[2].split(b"\r\n\r\n", 1)[1][:-2]
                number = metadata["FPID"]
                state["photos"][number] = photo + (b"changed" if state["recompress"] else b"")
                state["persons"][number].update(numOfFace=1, faceURL=state["base_url"]+"/LOCALS/pic/enrlFace/"+number)
            elif path.endswith("/UserInfoDetail/Delete"):
                info = json.loads(body)["UserInfoDetail"]
                assert info["mode"] == "byEmployeeNo" and len(info["EmployeeNoList"]) == 1
                number = info["EmployeeNoList"][0]["employeeNo"]
                state["persons"].pop(number, None)
                if not state["residual_credentials"]: state["photos"].pop(number, None)
            else:
                return self.respond({"statusCode": 4, "statusString": "Unknown command"}, 404)
            if state["drop_after"] == path:
                self.connection.shutdown(2); self.connection.close(); return
            return self.respond({"statusCode": 1, "statusString": "OK"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    state["base_url"] = f"https://127.0.0.1:{server.server_port}"
    state["pin"] = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    state["photo"] = image.getvalue()
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield state
    server.shutdown(); server.server_close(); thread.join(timeout=3)


def device(state): return LiveDevice(state["base_url"], state["pin"], "synthetic-user", "synthetic-password")


def policy():
    return {"validity": {"enabled": True, "begin": "2026-01-01T00:00:00", "end": "2027-01-01T00:00:00"},
        "right_plans": [{"door_no": 1, "plan_template_no": "1"}]}


def add_person(state, number="TEST-1", name="Synthetic Person"):
    native_policy = policy()
    state["persons"][number] = {"employeeNo": number, "name": name, "userType": "normal",
        "Valid": {"enable": True, "beginTime": native_policy["validity"]["begin"], "endTime": native_policy["validity"]["end"], "timeType": "local"},
        "doorRight": "1", "RightPlan": [{"doorNo": 1, "planTemplateNo": "1"}], "numOfFace": 1, "numOfCard": 0,
        "numOfFP": 0, "localUIRight": False, "doubleLockRight": False,
        "faceURL": state["base_url"]+"/LOCALS/pic/enrlFace/"+number}
    state["photos"][number] = state["photo"]


class MemoryJournal:
    def __init__(self): self.records = {}; self.saves = 0
    def save(self, key, value):
        self.saves += 1; self.records[key] = json.loads(json.dumps(value))
    def pending(self): return [(k, v) for k, v in self.records.items() if v["phase"] != "acknowledged"]


class FakeERP:
    def __init__(self, job, photo): self.job = job; self.photo_bytes = photo; self.permits = []; self.results = []
    def claim(self): job, self.job = self.job, None; return job
    def photo(self, job): return self.photo_bytes
    def dispatch(self, job, step):
        assert step not in self.permits; self.permits.append(step)
    def result(self, job, result):
        self.results.append(result)
        return {"state": "succeeded" if result["outcome"] == "readback" else "uncertain"}


def worker(state, action, *, baseline=None, write_approved=True):
    job = {"job_id": 1, "device_key": "synthetic", "source_host": "127.0.0.1", "certificate_sha256": state["pin"],
        "external_person_id": "TEST-1", "action": action, "lease_token": "x"*48,
        "lease_expires_at": (datetime.now(timezone.utc)+timedelta(seconds=150)).isoformat(), "face_library_id": "1",
        "baseline": baseline, "desired_name": "Synthetic New" if action == "enroll" else "Edited" if action == "edit" else None,
        "desired_policy": policy() if action == "enroll" else None, "photo_asset_id": 1 if action in ("enroll", "photo") else None,
        "photo_sha256": hashlib.sha256(state["photo"]).hexdigest() if action in ("enroll", "photo") else None}
    erp = FakeERP(job, state["photo"]); journal = MemoryJournal()
    config = {"device_key": "synthetic", "hikvision_base_url": state["base_url"], "hikvision_cert_sha256": state["pin"],
        "writes_enabled": True, "allowed_employee_numbers": ["TEST-1"]}
    return Worker(erp, config, journal, write_approved=write_approved), erp, journal


def test_pinned_digest_observation_without_writes(tls_device):
    add_person(tls_device)
    item, erp, journal = worker(tls_device, "observe")
    item.once()
    assert erp.results[0]["after"]["photo_sha256"] == hashlib.sha256(tls_device["photo"]).hexdigest()
    assert erp.permits == tls_device["writes"] == []
    assert tls_device["digest_challenges"] > 0


def test_wrong_pin_prevents_http_and_authentication(tls_device):
    source = LiveDevice(tls_device["base_url"], "0"*64, "synthetic", "secret")
    with pytest.raises(DeviceRefusal, match="pin mismatch"): source.capabilities()
    assert tls_device["requests"] == [] and tls_device["digest_challenges"] == 0


def test_digest_error_budget_resets_for_each_independent_request(tls_device):
    source=device(tls_device);tls_device["http_error"]=400
    for _ in range(8):
        with pytest.raises(DeviceRefusal,match="HTTP status 400"):source.capabilities()
    tls_device["http_error"]=None
    assert source.capabilities()["isSupportUserInfo"] is True
    assert len(tls_device["requests"])==9 and tls_device["writes"]==[]


def test_face_readback_falls_back_to_exact_root_fpid_search(tls_device):
    add_person(tls_device);tls_device["persons"]["TEST-1"].pop("faceURL")
    result=device(tls_device).snapshot("TEST-1","1")
    assert result["photo_sha256"]==hashlib.sha256(tls_device["photo"]).hexdigest()
    assert ("POST","/ISAPI/Intelligent/FDLib/FDSearch") in tls_device["requests"]
    assert not tls_device["writes"]


@pytest.mark.parametrize("location", ["https://127.0.0.1:1/steal", "/ISAPI/AccessControl/UserInfoDetail/Delete?format=json"])
def test_redirect_never_reaches_second_endpoint(tls_device, location):
    tls_device["redirect"] = location
    with pytest.raises(DeviceRefusal, match="redirect"): device(tls_device).capabilities()
    assert len(tls_device["requests"]) == 1 and tls_device["writes"] == []


@pytest.mark.parametrize("action", ["enroll", "edit", "photo", "revoke", "delete"])
def test_local_default_refuses_all_writes(tls_device, action):
    item, erp, _ = worker(tls_device, action, write_approved=False)
    item.once()
    assert erp.results[0]["outcome"] == "refused" and tls_device["writes"] == erp.permits == []


def test_new_enrollment_activates_only_after_exact_blocked_photo_readback(tls_device):
    item, erp, _ = worker(tls_device, "enroll")
    item.once()
    assert erp.permits == ["create_blocked_person", "upload_face", "activate_access"]
    assert erp.results[0]["vendor_accepted"] and erp.results[0]["after"]["user_type"] == "normal"
    assert len(tls_device["writes"]) == 3


def test_complete_capabilities_allow_omission_of_unadvertised_optional_permission(tls_device):
    tls_device["privilege_capabilities"].pop("doubleLockRight")
    item, erp, _ = worker(tls_device, "enroll"); item.once()
    after = erp.results[0]["after"]
    assert erp.results[0]["outcome"] == "readback"
    assert after["local_ui_right"] is False and after["double_lock_right"] is None
    assert after["security_capabilities"]["double_lock"] == "not_advertised"
    assert len(after["security_capabilities"]["user_info_sha256"]) == 64
    assert "doubleLockRight" not in tls_device["persons"]["TEST-1"]
    assert erp.permits == ["create_blocked_person", "upload_face", "activate_access"]


def test_unadvertised_permission_returning_true_never_activates(tls_device):
    tls_device["privilege_capabilities"].pop("doubleLockRight")
    tls_device["record_flags"] = {"doubleLockRight": True}
    item, erp, _ = worker(tls_device, "enroll"); item.once()
    assert erp.results[0]["outcome"] == "unknown"
    assert erp.permits == ["create_blocked_person"]
    assert tls_device["persons"]["TEST-1"]["userType"] == "blackList"


@pytest.mark.parametrize("field", ["employeeNo", "userType", "Valid", "RightPlan", "UserInfoSearchCond", "localUIRight"])
def test_incomplete_capability_never_means_optional_permission_is_safe(tls_device, field):
    tls_device["privilege_capabilities"].pop("doubleLockRight")
    tls_device["privilege_capabilities"].pop(field)
    item, erp, _ = worker(tls_device, "enroll"); item.once()
    assert erp.results[0]["outcome"] == "refused"
    assert not erp.permits and not tls_device["writes"]


@pytest.mark.parametrize("field", ["Valid", "RightPlan"])
@pytest.mark.parametrize("value", [{}, [], "true", True])
def test_malformed_policy_capability_is_not_complete_evidence(tls_device, field, value):
    tls_device["privilege_capabilities"].pop("doubleLockRight")
    tls_device["privilege_capabilities"][field] = value
    item, erp, _ = worker(tls_device, "enroll"); item.once()
    assert erp.results[0]["outcome"] == "refused"
    assert not erp.permits and not tls_device["writes"]


def test_capability_change_after_creation_leaves_profile_blocked(tls_device, monkeypatch):
    item, erp, _ = worker(tls_device, "enroll")
    original = LiveDevice.create_blocked_person
    def create_then_drift(self, *args, **kwargs):
        original(self, *args, **kwargs)
        tls_device["privilege_capabilities"]["doubleLockRight"] = {"@opt": "true,false"}
    monkeypatch.setattr(LiveDevice, "create_blocked_person", create_then_drift)
    item.once()
    assert erp.results[0]["outcome"] == "unknown" and erp.permits == ["create_blocked_person"]
    assert tls_device["persons"]["TEST-1"]["userType"] == "blackList"


def test_photo_mismatch_leaves_new_profile_blocked(tls_device):
    tls_device["recompress"] = True
    item, erp, _ = worker(tls_device, "enroll")
    item.once()
    assert erp.results[0]["outcome"] == "unknown"
    assert tls_device["persons"]["TEST-1"]["userType"] == "blackList"
    assert erp.permits == ["create_blocked_person", "upload_face"]


def test_capacity_failure_is_before_person_creation(tls_device):
    tls_device["capacity"] = 0
    item, erp, _ = worker(tls_device, "enroll"); item.once()
    assert erp.results[0]["outcome"] == "refused" and not tls_device["writes"]


@pytest.mark.parametrize("rows", [[], [{"FDID": "2", "faceLibType": "blackFD", "recordDataNumber": 0}],
    [{"FDID": "1", "faceLibType": "infraredFD", "recordDataNumber": 0}],
    [{"FDID": "1", "faceLibType": "blackFD", "recordDataNumber": n} for n in (0, 1)],
    *[[{"FDID": "1", "faceLibType": "blackFD", "recordDataNumber": n}] for n in (-1, 1500, True, "1399")]])
def test_face_count_requires_exact_unique_typed_library(tls_device, rows):
    tls_device["count_response"] = {"statusCode": 1, "statusString": "OK", "FDRecordDataInfo": rows}
    with pytest.raises(DeviceRefusal): device(tls_device).face_capacity("1")
    assert not tls_device["writes"]


def test_capacity_uses_count_without_firmware_face_search(tls_device):
    device(tls_device).face_capacity("1")
    assert ("GET", "/ISAPI/Intelligent/FDLib/Count") in tls_device["requests"]
    assert not any(path.endswith("/FDSearch") for _, path in tls_device["requests"])


@pytest.mark.parametrize("flags", [{"localUIRight": True}, {"doubleLockRight": True},
    {"localUIRight": None}, {"doubleLockRight": None}])
def test_new_profile_unverified_privileges_never_activate(tls_device, flags):
    tls_device["record_flags"] = flags
    item, erp, _ = worker(tls_device, "enroll"); item.once()
    assert erp.results[0]["outcome"] == "unknown"
    assert erp.permits == ["create_blocked_person"]
    assert tls_device["persons"]["TEST-1"]["userType"] == "blackList"


@pytest.mark.parametrize("field", ["numOfFace", "numOfCard", "numOfFP"])
def test_missing_credential_counter_never_becomes_zero_evidence(tls_device, field):
    tls_device["record_flags"] = {field: None}
    item, erp, _ = worker(tls_device, "enroll"); item.once()
    assert erp.results[0]["outcome"] == "unknown" and erp.permits == ["create_blocked_person"]
    assert tls_device["persons"]["TEST-1"]["userType"] == "blackList"


@pytest.mark.parametrize("capabilities", [{"localUIRight":"true,false"}, {"doubleLockRight":"true,false"},
    {"localUIRight":"true,false","doubleLockRight":"true"}])
def test_unavailable_privilege_capability_refuses_before_profile_creation(tls_device, capabilities):
    tls_device["privilege_capabilities"]=capabilities
    item,erp,_=worker(tls_device,"enroll");item.once()
    assert erp.results[0]["outcome"]=="refused" and not erp.permits and not tls_device["writes"]
    assert "TEST-1" not in tls_device["persons"]


def test_observation_outside_local_allowlist_makes_no_physical_request(tls_device):
    item, erp, _ = worker(tls_device, "observe")
    item.config["allowed_employee_numbers"] = []
    item.once()
    assert erp.results[0]["outcome"] == "refused"
    assert tls_device["requests"] == tls_device["writes"] == []


def test_recovery_outside_local_allowlist_makes_no_physical_request(tls_device):
    item, erp, journal = worker(tls_device, "observe")
    claim = erp.job.copy(); erp.job = None
    journal.save("1-" + "a"*16, {"phase": "dispatching", "claim": claim})
    item.config["allowed_employee_numbers"] = []
    item.once()
    assert erp.results[0]["outcome"] == "unknown"
    assert tls_device["requests"] == tls_device["writes"] == []


@pytest.mark.parametrize("residual", ["face", "card", "fingerprint"])
def test_delete_profile_absence_does_not_hide_residual_credentials(tls_device, residual):
    add_person(tls_device); tls_device["persons"]["TEST-1"]["userType"] = "blackList"
    if residual == "face": tls_device["residual_credentials"] = True
    if residual == "card": tls_device["card_residual"] = 1
    if residual == "fingerprint": tls_device["fp_residual"] = 1
    item, erp, _ = worker(tls_device, "delete", baseline=device(tls_device).snapshot("TEST-1", "1"))
    item.once()
    assert "TEST-1" not in tls_device["persons"]
    assert erp.results[0]["outcome"] == "unknown"
    assert erp.permits == ["delete_profile"]


@pytest.mark.parametrize("status", ["failed", "processing", "invalid", "idle"])
def test_delete_never_repeats_when_progress_cannot_complete(tls_device, status, monkeypatch):
    monkeypatch.setattr("live_worker.time.sleep", lambda _: None)
    add_person(tls_device); tls_device["persons"]["TEST-1"]["userType"] = "blackList"
    tls_device["delete_status"] = ["success", status]
    item, erp, _ = worker(tls_device, "delete", baseline=device(tls_device).snapshot("TEST-1", "1"))
    item.once()
    assert erp.results[0]["outcome"] == "unknown" and erp.permits == ["delete_profile"]
    assert len(tls_device["writes"]) == 1


def test_idle_native_error_allows_one_delete_then_requires_explicit_success(tls_device, monkeypatch):
    monkeypatch.setattr("live_worker.time.sleep", lambda _: None)
    add_person(tls_device); tls_device["persons"]["TEST-1"]["userType"] = "blackList"
    tls_device["delete_status"] = ["idle", "idle", "processing", "success"]
    item, erp, _ = worker(tls_device, "delete", baseline=device(tls_device).snapshot("TEST-1", "1"))
    item.once()
    assert erp.results[0]["outcome"] == "readback" and not erp.results[0]["after"]["present"]
    assert erp.permits == ["delete_profile"] and len(tls_device["writes"]) == 1


@pytest.mark.parametrize("body", [{}, {"statusCode": 4},
    {"statusCode": 4, "subStatusCode": "notSupported", "errorCode": 1073746095},
    {"statusCode": 4, "subStatusCode": "taskNotExist", "errorCode": 0},
    {"statusCode": "4", "subStatusCode": "taskNotExist", "errorCode": 1073746095},
    {"statusCode": 4, "subStatusCode": "taskNotExist", "errorCode": "1073746095"},
    {"statusCode": 3, "subStatusCode": "deviceError", "errorCode": 805306369},
    b"not JSON", {"ResponseStatus": []}])
def test_other_404_responses_never_become_idle_or_success(tls_device, body):
    tls_device["delete_error"] = body
    with pytest.raises(DeviceRefusal, match="HTTP status 404"):
        device(tls_device).deletion_status()
    assert not tls_device["writes"]


def test_idle_progress_is_distinct_from_completed_deletion(tls_device):
    from live_device import DeleteProgress
    tls_device["delete_status"] = "idle"
    assert device(tls_device).deletion_status() is DeleteProgress.IDLE
    assert not tls_device["writes"]


def test_invalid_employee_number_is_never_absence_evidence(tls_device):
    tls_device["invalid_identity"] = True
    with pytest.raises(DeviceRefusal, match="HTTP status 400"):
        device(tls_device).snapshot("INVALID-LONG-TEST-ID", "1")
    assert not tls_device["writes"]


def test_busy_delete_process_is_refused_before_dispatch(tls_device):
    add_person(tls_device); tls_device["persons"]["TEST-1"]["userType"] = "blackList"
    tls_device["delete_status"] = "processing"
    item, erp, _ = worker(tls_device, "delete", baseline=device(tls_device).snapshot("TEST-1", "1"))
    item.once()
    assert erp.results[0]["outcome"] == "refused" and not erp.permits and not tls_device["writes"]


def test_lane_error_does_not_starve_later_devices(tmp_path, monkeypatch, capsys):
    import live_worker
    journal=tmp_path/"journal";journal.mkdir()
    config=tmp_path/"private.json"
    config.write_text(json.dumps({"erp_base_url":"https://example.invalid","writer_journal_dir":str(journal),
        "devices":[{"device_key":key,"worker_token_env":key} for key in ("bad","good")]}),encoding="utf-8")
    seen=[]
    class LocalERP:
        def __init__(self,base_url,token):
            if token=="bad-secret":raise RuntimeError("bad-secret must not appear")
        def close(self):seen.append("closed")
    class LocalWorker:
        def __init__(self,erp,device,journal,**kwargs):seen.append(device["device_key"])
        def once(self):return None
    monkeypatch.setattr(live_worker,"ERP",LocalERP);monkeypatch.setattr(live_worker,"Worker",LocalWorker)
    monkeypatch.setattr(live_worker,"ProtectedJournal",lambda root:MemoryJournal())
    monkeypatch.setenv("bad","bad-secret");monkeypatch.setenv("good","good-secret")
    monkeypatch.setattr("sys.argv",["live_worker.py","--config",str(config)])
    assert live_worker.main()==1
    assert seen==["good","closed"] and not (journal/"worker.lock").exists()
    output=capsys.readouterr().out
    assert '"worker_error"' in output and '"idle"' in output and "secret" not in output


@pytest.mark.parametrize("action", ["edit", "photo", "revoke", "delete"])
def test_baseline_drift_sends_no_mutation(tls_device, action):
    add_person(tls_device); before = device(tls_device).snapshot("TEST-1", "1")
    tls_device["persons"]["TEST-1"]["localUIRight"] = True
    item, erp, _ = worker(tls_device, action, baseline=before); item.once()
    assert not erp.permits and not tls_device["writes"] and not erp.results[0]["vendor_accepted"]


def test_revoke_preserves_credentials_then_delete_is_exact(tls_device):
    add_person(tls_device); add_person(tls_device, "OTHER")
    before = device(tls_device).snapshot("TEST-1", "1")
    item, erp, _ = worker(tls_device, "revoke", baseline=before); item.once()
    revoked = erp.results[0]["after"]
    assert revoked == {**before, "user_type": "blackList"}
    assert "TEST-1" in tls_device["photos"]
    item, erp, _ = worker(tls_device, "delete", baseline=revoked); item.once()
    assert erp.results[0]["after"]["present"] is False
    assert "OTHER" in tls_device["persons"] and "OTHER" in tls_device["photos"]


def test_timeout_after_acceptance_never_retries_write(tls_device):
    add_person(tls_device); before = device(tls_device).snapshot("TEST-1", "1")
    tls_device["drop_after"] = "/ISAPI/AccessControl/UserInfo/Modify"
    item, erp, journal = worker(tls_device, "edit", baseline=before); item.once()
    assert erp.results[0]["outcome"] == "unknown" and len(tls_device["writes"]) == 1
    item.once(); assert len(tls_device["writes"]) == 1


def test_crashed_journal_recovers_read_only(tls_device):
    add_person(tls_device); before = device(tls_device).snapshot("TEST-1", "1")
    item, erp, journal = worker(tls_device, "edit", baseline=before)
    job = erp.claim(); journal.save("1-"+"a"*16, {"claim": job, "phase": "dispatching", "before": before})
    item.once()
    assert not tls_device["writes"] and not erp.permits and erp.results[0]["outcome"] == "unknown"


@pytest.mark.parametrize("url", ["http://127.0.0.1", "https://example.com", "https://u:p@127.0.0.1", "https://127.0.0.1/path", "https://127.0.0.1:0"])
def test_device_origin_scope(url):
    with pytest.raises(DeviceRefusal): LiveDevice(url, "a"*64, "u", "p")


def test_real_windows_journal_is_protected_and_round_trips(tmp_path):
    import os
    if os.name != "nt": pytest.skip("Windows DPAPI is a separate platform gate")
    journal = ProtectedJournal(tmp_path/"writer")
    secret = {"phase": "claimed", "claim": {"lease_token": "never-plaintext"}}
    journal.save("1-"+"a"*16, secret)
    assert b"never-plaintext" not in next(journal.root.glob("*.dpapi")).read_bytes()
    assert journal.pending() == [("1-"+"a"*16, secret)]
