"""One-shot LAN worker. Never installs, schedules or activates itself.

Use a separate private writer configuration/journal. The installed read-only
attendance reader and its state are never opened or modified by this module.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import uuid
import httpx
from live_device import LiveDevice, DeviceRefusal

PREFIX = "/api/turnstile-live/worker"
ACTIONS = {"observe", "enroll", "edit", "photo", "revoke", "restore", "delete"}


def _dpapi(data: bytes, *, decrypt=False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("The production writer journal requires Windows DPAPI")
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
    storage = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), storage); output = Blob()
    operation = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError("Writer journal protection failed")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(output.pbData)


class ProtectedJournal:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def save(self, name: str, value: dict) -> None:
        if not re.fullmatch(r"[0-9]+-[0-9a-f]{16}", name):
            raise RuntimeError("Invalid journal key")
        encrypted = _dpapi(json.dumps(value, separators=(",", ":")).encode())
        path = self.root / (name + ".dpapi"); temporary = self.root / (uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(encrypted); stream.flush(); os.fsync(stream.fileno())
            # Write-through rename commits the dispatch marker before device I/O.
            ctypes.windll.kernel32.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
            if not ctypes.windll.kernel32.MoveFileExW(str(temporary), str(path), 0x1 | 0x8):
                raise RuntimeError("Writer journal commit failed")
        finally:
            if temporary.exists(): temporary.unlink()

    def pending(self) -> list[tuple[str, dict]]:
        records = []
        for path in sorted(self.root.glob("*.dpapi")):
            value = json.loads(_dpapi(path.read_bytes(), decrypt=True))
            if value.get("phase") != "acknowledged": records.append((path.stem, value))
        return records


class ERP:
    def __init__(self, base_url: str, token: str, *, transport=None):
        origin = urlparse(base_url)
        if origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.path not in ("", "/") or origin.query or origin.fragment:
            raise RuntimeError("A verified HTTPS ERP origin is required")
        if not token: raise RuntimeError("A dedicated device worker token is required")
        self.client = httpx.Client(base_url=base_url.rstrip("/"), headers={"X-Turnstile-Worker-Token": token},
            timeout=20, follow_redirects=False, trust_env=False, transport=transport)

    def _json(self, method: str, path: str, **kwargs):
        response = self.client.request(method, PREFIX + path, **kwargs)
        response.raise_for_status()
        return response.json()

    def claim(self): return self._json("POST", "/claim")

    def dispatch(self, job: dict, step: str):
        value = self._json("POST", f"/jobs/{job['job_id']}/dispatch", json={"step": step}, headers={"X-Turnstile-Lease": job["lease_token"]})
        if value != {"permitted": True}: raise RuntimeError("Write permit was not granted")

    def result(self, job: dict, result: dict):
        return self._json("POST", f"/jobs/{job['job_id']}/result", json={"lease_token": job["lease_token"], **result})

    def photo(self, job: dict) -> bytes:
        with self.client.stream("GET", PREFIX + f"/jobs/{job['job_id']}/photo", headers={"X-Turnstile-Lease": job["lease_token"]}) as response:
            response.raise_for_status(); data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 8 * 1024 * 1024: raise RuntimeError("Assigned photo exceeds limit")
        content = bytes(data)
        if hashlib.sha256(content).hexdigest() != job["photo_sha256"] or not content.startswith(b"\xff\xd8"):
            raise RuntimeError("Assigned photo integrity failed")
        return content

    def close(self): self.client.close()


class Worker:
    def __init__(self, erp, device_config: dict, journal, *, write_approved=False, device_factory=LiveDevice):
        self.erp = erp; self.config = device_config; self.journal = journal
        self.write_approved = write_approved; self.device_factory = device_factory

    def _device(self, job: dict):
        if (job.get("action") not in ACTIONS or type(job.get("job_id")) is not int or job["job_id"] <= 0
                or not isinstance(job.get("lease_token"), str) or len(job["lease_token"]) < 32
                or job.get("device_key") != self.config["device_key"]):
            raise RuntimeError("Unrecognized or incorrectly scoped worker claim")
        number = job.get("external_person_id")
        if (not isinstance(number, str) or not number or number != number.strip() or len(number.encode()) > 32
                or any(ord(c) < 32 for c in number) or number not in self.config.get("allowed_employee_numbers", [])):
            raise DeviceRefusal("The exact identity must be in the local read/write allowlist")
        configured = urlparse(self.config["hikvision_base_url"])
        if configured.hostname != job["source_host"] or self.config["hikvision_cert_sha256"] != job["certificate_sha256"]:
            raise RuntimeError("Claim does not match the locally approved device and pin")
        return self.device_factory(self.config["hikvision_base_url"], self.config["hikvision_cert_sha256"],
            os.environ.get("HIKVISION_USERNAME", ""), os.environ.get("HIKVISION_PASSWORD", ""))

    @staticmethod
    def _deadline(job: dict):
        expires = datetime.fromisoformat(job["lease_expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
            raise RuntimeError("Worker lease expired; no further write is allowed")

    def _send(self, key: str, record: dict, step: str, operation):
        job = record["claim"]
        self._deadline(job)
        # Persist before requesting the single-use permit. A lost permit response
        # also means read-only recovery, never a second mutation attempt.
        record.update(phase="dispatching", last_step=step)
        self.journal.save(key, record)
        self.erp.dispatch(job, step)
        self._deadline(job)
        operation()
        record["accepted_steps"] = [*record.get("accepted_steps", []), step]
        self.journal.save(key, record)

    def _finish(self, key: str, record: dict, result: dict):
        record.update(phase="result_ready", result=result)
        self.journal.save(key, record)
        response = self.erp.result(record["claim"], result)
        record.update(phase="acknowledged", server_state=response["state"])
        self.journal.save(key, record)
        return response

    def recover(self, key: str, record: dict):
        if record["claim"]["device_key"] != self.config["device_key"]:
            return None
        if record.get("phase") == "result_ready":
            return self._finish(key, record, record["result"])
        # A journal from a crashed process is never resumed as a write sequence.
        job = record["claim"]; after = None
        try:
            after = self._device(job).snapshot(job["external_person_id"], job["face_library_id"])
        except Exception:
            pass
        return self._finish(key, record, {"outcome": "unknown", "before": record.get("before"),
            "after": after, "vendor_accepted": False, "worker_quiescent": True})

    def once(self):
        pending = self.journal.pending()
        matching = [(k, r) for k, r in pending if r.get("claim", {}).get("device_key") == self.config["device_key"]]
        if matching:
            return self.recover(*matching[0])
        job = self.erp.claim()
        if job is None: return None
        key = f"{job['job_id']}-{hashlib.sha256(job['lease_token'].encode()).hexdigest()[:16]}"
        record = {"claim": job, "phase": "claimed", "accepted_steps": []}
        self.journal.save(key, record)
        before = after = None
        try:
            device = self._device(job); number = job["external_person_id"]; library = job["face_library_id"]
            if job["action"] != "observe" and (not self.write_approved or not self.config.get("writes_enabled", False)
                    or number not in self.config.get("allowed_employee_numbers", [])):
                raise DeviceRefusal("Local writer approval and explicit identity scope are required")
            self._deadline(job)
            capabilities = device.capabilities()
            before = after = device.snapshot(number, library)
            record["before"] = before; self.journal.save(key, record)
            if job["action"] == "observe":
                return self._finish(key, record, {"outcome": "readback", "before": None, "after": after, "vendor_accepted": False, "worker_quiescent": True})
            if job["action"] == "enroll":
                if before["present"]:
                    return self._finish(key, record, {"outcome": "readback", "before": before, "after": after, "vendor_accepted": False, "worker_quiescent": True})
            elif before != job["baseline"]:
                return self._finish(key, record, {"outcome": "readback", "before": before, "after": after, "vendor_accepted": False, "worker_quiescent": True})
            action = job["action"]
            if action in ("enroll", "photo"):
                if capabilities.get("isSupportFDLib") is not True: raise DeviceRefusal("Face management is unsupported")
                photo = self.erp.photo(job)
                if action == "enroll" or not before["face_count"]: device.face_capacity(library)
                if action == "enroll": device.enrollment_capabilities()
            if action == "enroll":
                self._send(key, record, "create_blocked_person", lambda: device.create_blocked_person(number, job["desired_name"], job["desired_policy"]))
                blocked = device.snapshot(number, library)
                if (not blocked["present"] or blocked["user_type"] != "blackList" or blocked["full_name"] != job["desired_name"]
                        or blocked["policy"] != job["desired_policy"] or blocked["face_count"] or blocked["card_count"] or blocked["fingerprint_count"]
                        or blocked.get("local_ui_right") is not False or blocked.get("double_lock_right") is not False):
                    raise DeviceRefusal("New blocked profile readback did not match")
                self._send(key, record, "upload_face", lambda: device.upload_face(number, library, photo, replace=False))
                faced = device.snapshot(number, library)
                expected = {**blocked, "face_count": 1, "photo_sha256": job["photo_sha256"]}
                if faced != expected: raise DeviceRefusal("Blocked photo readback did not match; access stays blocked")
                self._send(key, record, "activate_access", lambda: device.modify_person(number, {"userType": "normal"}))
            elif action == "edit":
                self._send(key, record, "modify_profile", lambda: device.modify_person(number, {"name": job["desired_name"]}))
            elif action == "photo":
                self._send(key, record, "upload_face", lambda: device.upload_face(number, library, photo, replace=bool(before["face_count"])))
            elif action == "revoke":
                self._send(key, record, "modify_profile", lambda: device.modify_person(number, {"userType": "blackList"}))
            elif action == "restore":
                if before["user_type"] != "blackList" or before["face_count"] != 1 or before["policy"] != job["desired_policy"]:
                    raise DeviceRefusal("Restore needs a verified blocked face profile and exactly approved access policy")
                self._send(key, record, "modify_profile", lambda: device.modify_person(number, {"userType": "normal"}))
            elif action == "delete":
                if before["user_type"] != "blackList" or capabilities.get("isSupportUserInfoDetailDelete") is not True:
                    raise DeviceRefusal("Revoke access and verify exact deletion capability first")
                # Verify every required read route before submitting the only
                # deletion command. Unsupported firmware stays unchanged.
                counts = device.credential_counts(number, library)
                if any(counts[field] != before[field] for field in counts):
                    raise DeviceRefusal("Credential inventory disagrees with the reviewed profile")
                if device.deletion_status() == "processing":
                    raise DeviceRefusal("Another deletion is still processing; no command was sent")
                self._send(key, record, "delete_profile", lambda: device.delete_revoked_person(number))
                completed = False
                for attempt in range(10):
                    self._deadline(job)
                    status = device.deletion_status()
                    if status == "success": completed = True; break
                    if status == "failed": raise DeviceRefusal("Device reports deletion failure")
                    if attempt < 9: time.sleep(1)
                if not completed: raise DeviceRefusal("Deletion completion remains unknown")
                if any(device.credential_counts(number, library).values()):
                    raise DeviceRefusal("Residual credentials remain after profile deletion")
            after = device.snapshot(number, library)
            return self._finish(key, record, {"outcome": "readback", "before": before, "after": after, "vendor_accepted": True, "worker_quiescent": True,
                "delete_completed": action == "delete", "credentials_absent": action == "delete"})
        except Exception:
            # Keep diagnostics non-personal. Never log device bodies, URL tokens,
            # names, credentials or images, and never repeat a write here.
            if record.get("phase") in ("result_ready", "acknowledged"):
                raise
            return self._finish(key, record, {"outcome": "unknown" if record.get("phase") == "dispatching" else "refused",
                "before": before, "after": after, "vendor_accepted": False, "worker_quiescent": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--approve-device-writes", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    root = Path(config["writer_journal_dir"]).resolve()
    if root == args.config.parent.resolve() or root.name in ("HikvisionAttendance", "state.json"):
        raise RuntimeError("A separate writer journal directory is required")
    journal = ProtectedJournal(root)
    lock = root / "worker.lock"
    # Never steal a stale lock. Operator must stop the former worker, then review
    # and remove this exact lock. Pending journals recover only through reads.
    with lock.open("x", encoding="ascii") as stream:
        stream.write(str(os.getpid())); stream.flush(); os.fsync(stream.fileno())
    failed = False
    try:
        for device in config["devices"]:
            erp = None
            try:
                erp = ERP(config["erp_base_url"], os.environ.get(device["worker_token_env"], ""))
                result = Worker(erp, device, journal, write_approved=args.approve_device_writes).once()
                print(json.dumps({"device_key": device["device_key"], "state": result["state"] if result else "idle"}), flush=True)
                if result and result["state"] != "succeeded": failed = True
            except Exception:
                # A lane failure must not starve later independent lanes. Keep
                # private config, tokens, HTTP bodies and exception text out.
                failed = True
                print(json.dumps({"device_key": device.get("device_key"), "state": "worker_error"}), flush=True)
            finally:
                if erp is not None: erp.close()
    finally:
        lock.unlink()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
