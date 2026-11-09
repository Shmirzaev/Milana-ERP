"""Pinned ISAPI transport for the separately activated physical worker.

No arbitrary commands, redirects, subscriptions, device settings or write retry.
Each HTTPS connection verifies the configured certificate before sending HTTP.
"""
from __future__ import annotations
import hashlib
import http.client
import ipaddress
import json
import ssl
import uuid
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
import xml.etree.ElementTree as ET

MAX_BYTES = 8 * 1024 * 1024
SEARCH = "/ISAPI/AccessControl/UserInfo/Search?format=json"
GET_PATHS = {"/ISAPI/AccessControl/capabilities", "/ISAPI/AccessControl/UserInfo/capabilities?format=json", "/ISAPI/Intelligent/FDLib/capabilities?format=json", "/ISAPI/Intelligent/FDLib/Count?format=json",
    "/ISAPI/AccessControl/UserInfoDetail/DeleteProcess?format=json"}
READ_POSTS = {SEARCH, "/ISAPI/Intelligent/FDLib/FDSearch?format=json", "/ISAPI/AccessControl/CardInfo/Search?format=json",
    "/ISAPI/AccessControl/FingerPrintUpload?format=json"}
WRITE_PATHS = {
    ("POST", "/ISAPI/AccessControl/UserInfo/Record?format=json"),
    ("PUT", "/ISAPI/AccessControl/UserInfo/Modify?format=json"),
    ("POST", "/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json"),
    ("PUT", "/ISAPI/Intelligent/FDLib/FDSetUp?format=json"),
    ("PUT", "/ISAPI/AccessControl/UserInfoDetail/Delete?format=json"),
}


class DeviceRefusal(RuntimeError):
    """Protocol/capability refusal without including a personal device response."""


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise DeviceRefusal("Device redirects are forbidden")


class PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, host, *, fingerprint, **kwargs):
        self.fingerprint = fingerprint
        super().__init__(host, **kwargs)

    def connect(self):
        super().connect()
        if not self.sock or hashlib.sha256(self.sock.getpeercert(binary_form=True)).hexdigest() != self.fingerprint:
            self.close()
            raise DeviceRefusal("Device certificate pin mismatch")


class PinnedHTTPS(HTTPSHandler):
    def __init__(self, fingerprint):
        # Trust is the mandatory per-connection SHA-256 pin, not the self-signed
        # device certificate's CA/name. The pin is checked before HTTP/auth data.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False; context.verify_mode = ssl.CERT_NONE
        context.set_ciphers("DEFAULT:@SECLEVEL=0")
        self.fingerprint = fingerprint
        super().__init__(context=context)

    def https_open(self, req):
        return self.do_open(lambda host, **kw: PinnedConnection(host, fingerprint=self.fingerprint, **kw), req, context=self._context, check_hostname=False)


def _xml(element):
    children = list(element)
    if not children:
        text = (element.text or "").strip()
        return {"true": True, "false": False}.get(text.lower(), text)
    value = {}
    for child in children:
        key = child.tag.rsplit("}", 1)[-1]
        item = _xml(child)
        if key in value:
            value[key] = [*value[key], item] if isinstance(value[key], list) else [value[key], item]
        else:
            value[key] = item
    return value


def decode(body: bytes) -> dict:
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        try:
            root = ET.fromstring(body)
            value = {root.tag.rsplit("}", 1)[-1]: _xml(root)}
        except ET.ParseError as exc:
            raise DeviceRefusal("Unrecognized device response") from exc
    if not isinstance(value, dict):
        raise DeviceRefusal("Expected a device response object")
    return value


def success(value: dict) -> bool:
    status = value.get("ResponseStatus", value)
    return str(status.get("statusCode")) == "1" and str(status.get("statusString", "")).lower() == "ok"


class LiveDevice:
    def __init__(self, base_url: str, fingerprint: str, username: str, password: str):
        origin = urlparse(base_url)
        try:
            address = ipaddress.ip_address(origin.hostname or "")
        except ValueError as exc:
            raise DeviceRefusal("A private device IP is required") from exc
        if (origin.scheme != "https" or not address.is_private or origin.username or origin.password
                or origin.path not in ("", "/") or origin.query or origin.fragment or origin.port == 0
                or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint)):
            raise DeviceRefusal("Invalid pinned device origin")
        self.base_url = base_url.rstrip("/"); self.origin = origin; self.fingerprint = fingerprint
        manager = HTTPPasswordMgrWithDefaultRealm(); manager.add_password(None, self.base_url, username, password)
        self.digest_auth = HTTPDigestAuthHandler(manager)
        self.opener = build_opener(ProxyHandler({}), PinnedHTTPS(fingerprint), self.digest_auth, NoRedirect())

    def _photo_path(self, url: str) -> str:
        target = urlparse(urljoin(self.base_url + "/", url))
        if (target.scheme != "https" or target.hostname != self.origin.hostname
                or (target.port or 443) != (self.origin.port or 443) or target.port == 0
                or target.username or target.password or target.fragment
                or not target.path.startswith("/LOCALS/pic/enrlFace/")):
            raise DeviceRefusal("Face readback must stay on the pinned device")
        decoded = target.path
        for _ in range(8):
            if "\\" in decoded or any(p in (".", "..") for p in decoded.split("/")):
                raise DeviceRefusal("Unsafe face readback path")
            expanded = unquote(decoded)
            if expanded == decoded: break
            decoded = expanded
        else:
            raise DeviceRefusal("Excessive photo path encoding")
        return target.path + ("?" + target.query if target.query else "")

    def _request(self, method: str, path: str, body: bytes | None = None, content_type="application/json", *, write=False) -> bytes:
        if write:
            if (method, path) not in WRITE_PATHS:
                raise DeviceRefusal("Unapproved physical command")
        elif not ((method == "GET" and (path in GET_PATHS or path == self._photo_path(path))) or (method == "POST" and path in READ_POSTS)):
            raise DeviceRefusal("Unapproved physical read")
        req = Request(self.base_url + path, data=body, method=method, headers={"Content-Type": content_type, "Accept": "application/json"})
        # urllib does not reset this counter when an authenticated HTTP error
        # exits its handler. Each independent request keeps its own bounded
        # challenge budget; this does not retry a failed physical request.
        self.digest_auth.reset_retry_count()
        try:
            with self.opener.open(req, timeout=15) as response:
                if response.status != 200:
                    raise DeviceRefusal("Device did not return HTTP 200")
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise DeviceRefusal("Device response exceeds limit")
                return data
        except HTTPError as exc:
            exc.close()
            raise DeviceRefusal(f"Device HTTP status {exc.code}") from None

    def search(self, path: str, payload: dict) -> dict:
        return decode(self._request("POST", path, json.dumps(payload).encode()))

    def capabilities(self) -> dict:
        result = decode(self._request("GET", "/ISAPI/AccessControl/capabilities"))
        root = result.get("AccessControl", {})
        if root.get("isSupportUserInfo") is not True:
            raise DeviceRefusal("Person management capability is unavailable")
        return root

    def face_capacity(self, library_id: str) -> None:
        capabilities = decode(self._request("GET", "/ISAPI/Intelligent/FDLib/capabilities?format=json"))
        limit = capabilities.get("FDRecordDataMaxNum")
        if type(limit) is not int or limit <= 0:
            raise DeviceRefusal("Face capacity is unavailable")
        result = decode(self._request("GET", "/ISAPI/Intelligent/FDLib/Count?format=json"))
        if not success(result):
            raise DeviceRefusal("Face count was not accepted")
        libraries = result.get("FDRecordDataInfo")
        if not isinstance(libraries, list) or not libraries or any(not isinstance(row, dict) for row in libraries):
            raise DeviceRefusal("Complete face library counts are required")
        selected = [row for row in libraries if str(row.get("FDID")) == library_id and row.get("faceLibType") == "blackFD"]
        if len(selected) != 1:
            raise DeviceRefusal("Exact face library count is unavailable")
        count = selected[0].get("recordDataNumber")
        if type(count) is not int or count < 0 or count >= limit:
            raise DeviceRefusal("Face capacity is full or cannot be verified")

    def enrollment_capabilities(self) -> None:
        root = decode(self._request("GET", "/ISAPI/AccessControl/UserInfo/capabilities?format=json")).get("UserInfo", {})
        for field in ("localUIRight", "doubleLockRight"):
            options = root.get(field)
            if not isinstance(options, str) or "false" not in options.split(","):
                raise DeviceRefusal("New-profile privilege verification is unavailable; no profile was created")

    def modify_person(self, number: str, fields: dict) -> None:
        if set(fields) not in ({"name"}, {"userType"}):
            raise DeviceRefusal("Only reviewed name or access type may be modified")
        value = decode(self._request("PUT", "/ISAPI/AccessControl/UserInfo/Modify?format=json",
            json.dumps({"UserInfo": {"employeeNo": number, **fields}}).encode(), write=True))
        if not success(value): raise DeviceRefusal("Person modification was not accepted")

    def create_blocked_person(self, number: str, name: str, policy: dict) -> None:
        validity = policy["validity"]
        person = {"employeeNo": number, "name": name, "userType": "blackList",
            "Valid": {"enable": True, "beginTime": validity["begin"], "endTime": validity["end"], "timeType": "local"},
            "doorRight": ",".join(str(p["door_no"]) for p in policy["right_plans"]),
            "RightPlan": [{"doorNo": p["door_no"], "planTemplateNo": p["plan_template_no"]} for p in policy["right_plans"]],
            "localUIRight": False, "doubleLockRight": False}
        value = decode(self._request("POST", "/ISAPI/AccessControl/UserInfo/Record?format=json", json.dumps({"UserInfo": person}).encode(), write=True))
        if not success(value): raise DeviceRefusal("Blocked person creation was not accepted")

    def upload_face(self, number: str, library_id: str, photo: bytes, *, replace: bool) -> None:
        if len(photo) > MAX_BYTES or not photo.startswith(b"\xff\xd8"):
            raise DeviceRefusal("Validated bounded JPEG is required")
        metadata = json.dumps({"faceLibType": "blackFD", "FDID": library_id, "FPID": number}, ensure_ascii=True).encode()
        boundary = "MilanaFace" + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="FaceDataRecord"\r\nContent-Type: application/json\r\n\r\n'.encode()
            + metadata + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="FaceImage"; filename="face.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
            + photo + f'\r\n--{boundary}--\r\n'.encode())
        method, endpoint = ("PUT", "FDSetUp") if replace else ("POST", "FaceDataRecord")
        value = decode(self._request(method, f"/ISAPI/Intelligent/FDLib/{endpoint}?format=json", body,
            f"multipart/form-data; boundary={boundary}", write=True))
        if not success(value): raise DeviceRefusal("Face submission was not accepted")

    def delete_revoked_person(self, number: str) -> None:
        payload = {"UserInfoDetail": {"mode": "byEmployeeNo", "EmployeeNoList": [{"employeeNo": number}]}}
        value = decode(self._request("PUT", "/ISAPI/AccessControl/UserInfoDetail/Delete?format=json", json.dumps(payload).encode(), write=True))
        if not success(value): raise DeviceRefusal("Exact profile deletion was not accepted")

    def deletion_status(self) -> str:
        value = decode(self._request("GET", "/ISAPI/AccessControl/UserInfoDetail/DeleteProcess?format=json"))
        status = value.get("UserInfoDetailDeleteProcess", {}).get("status")
        if status not in ("processing", "success", "failed"):
            raise DeviceRefusal("Deletion progress cannot be verified")
        return status

    def credential_counts(self, number: str, library_id: str) -> dict:
        """Exact identity queries; return counts only, never credential material."""
        cond = {"searchID": uuid.uuid4().hex, "searchResultPosition": 0, "maxResults": 1}
        cards = self.search("/ISAPI/AccessControl/CardInfo/Search?format=json", {
            "CardInfoSearchCond": {**cond, "EmployeeNoList": [{"employeeNo": number}]}}).get("CardInfoSearch", {})
        faces = self.search("/ISAPI/Intelligent/FDLib/FDSearch?format=json", {
            **cond, "faceLibType": "blackFD", "FDID": library_id, "FPID": number})
        faces = faces.get("FDSearchResult", faces.get("FDSearch", faces))
        counts = {}
        for key, root, field in (("card_count", cards, "CardInfo"), ("face_count", faces, "MatchList")):
            count = root.get("totalMatches"); rows = root.get(field, [])
            if isinstance(rows, dict): rows = rows.get("MatchElement", rows) if field == "MatchList" else [rows]
            if isinstance(rows, dict): rows = [rows]
            if (type(count) is not int or count < 0 or not isinstance(rows, list)
                    or root.get("responseStatusStrg") not in ("OK", "NO MATCH")
                    or root.get("progress", 100) != 100 or len(rows) != min(count, 1)):
                raise DeviceRefusal("Complete credential query is unavailable")
            if rows and str(rows[0].get("employeeNo" if field == "CardInfo" else "FPID", rows[0].get("PID"))) != number:
                raise DeviceRefusal("Credential query returned another identity")
            counts[key] = count
        fingerprints = self.search("/ISAPI/AccessControl/FingerPrintUpload?format=json", {
            "FingerPrintCond": {"searchID": uuid.uuid4().hex, "employeeNo": number}}).get("FingerPrintInfo", {})
        status = fingerprints.get("status"); rows = fingerprints.get("FingerPrintList", [])
        if not isinstance(rows, list) or not ((status == "NoFP" and not rows) or (status == "OK" and rows)):
            raise DeviceRefusal("Complete fingerprint query is unavailable")
        counts["fingerprint_count"] = len(rows)
        return counts

    def snapshot(self, number: str, library_id: str) -> dict:
        if not number or len(number.encode()) > 32:
            raise DeviceRefusal("Employee number exceeds supported firmware limit")
        response = self.search(SEARCH, {"UserInfoSearchCond": {"searchID": uuid.uuid4().hex,
            "searchResultPosition": 0, "maxResults": 1, "EmployeeNoList": [{"employeeNo": number}]}})
        root = response.get("UserInfoSearch")
        if not isinstance(root, dict): raise DeviceRefusal("Missing person search result")
        count = int(root.get("totalMatches", -1)); persons = root.get("UserInfo", [])
        if isinstance(persons, dict): persons = [persons]
        empty = {"external_person_id": number, "present": False, "full_name": None,
            "user_type": None, "policy": None, "photo_sha256": None, "face_count": 0,
            "card_count": 0, "fingerprint_count": 0, "other_fields_hash": None,
            "local_ui_right": None, "double_lock_right": None}
        if count == 0 and not persons and str(root.get("responseStatusStrg", "")).upper() in ("NO MATCH", "OK"):
            return empty
        if count != 1 or len(persons) != 1 or persons[0].get("employeeNo") != number:
            raise DeviceRefusal("Person search is incomplete or ambiguous")
        person = persons[0]; valid = person.get("Valid", {})
        if any(type(person.get(field)) is not int or person[field] < 0 for field in ("numOfFace", "numOfCard", "numOfFP")):
            raise DeviceRefusal("Explicit typed credential counts are required")
        if any(person.get(flag) is not None and type(person[flag]) is not bool for flag in ("localUIRight", "doubleLockRight")):
            raise DeviceRefusal("Unrecognized physical security flags")
        if (not isinstance(valid.get("enable"), bool) or valid.get("timeType", "local") != "local"
                or person.get("userType") not in ("normal", "visitor", "blackList")):
            raise DeviceRefusal("Unsupported physical validity or person type")
        begin, end = (datetime.fromisoformat(valid[k]) for k in ("beginTime", "endTime"))
        if begin.tzinfo or end.tzinfo or end <= begin:
            raise DeviceRefusal("Unsupported physical validity window")
        plans = person.get("RightPlan", [])
        if not isinstance(plans, list) or not plans:
            raise DeviceRefusal("Complete door plans are required")
        plans = sorted([{"door_no": int(p["doorNo"]), "plan_template_no": str(p["planTemplateNo"])} for p in plans], key=lambda p: p["door_no"])
        if len({p["door_no"] for p in plans}) != len(plans) or set(str(person.get("doorRight", "")).split(",")) != {str(p["door_no"]) for p in plans}:
            raise DeviceRefusal("Door rights and plan assignments disagree")
        face_count = int(person.get("numOfFace", 0))
        if face_count not in (0, 1): raise DeviceRefusal("Multiple-face profiles require vendor review")
        photo_hash = None
        if face_count:
            photo_url = person.get("faceURL")
            if not photo_url:
                faces = self.search("/ISAPI/Intelligent/FDLib/FDSearch?format=json", {
                    "searchID": uuid.uuid4().hex, "searchResultPosition": 0, "maxResults": 1,
                    "faceLibType": "blackFD", "FDID": library_id, "FPID": number})
                root = faces.get("FDSearchResult", faces.get("FDSearch", faces))
                found = root.get("MatchList", [])
                if isinstance(found, dict):
                    found = found.get("MatchElement", [])
                if isinstance(found, dict): found = [found]
                if len(found) != 1 or str(found[0].get("FPID", found[0].get("PID"))) != number:
                    raise DeviceRefusal("Exact face readback is unavailable")
                photo_url = found[0].get("faceURL", found[0].get("picURL"))
            if not isinstance(photo_url, str) or not photo_url:
                raise DeviceRefusal("Face readback URL is unavailable")
            photo = self._request("GET", self._photo_path(photo_url))
            if not photo.startswith(b"\xff\xd8"):
                raise DeviceRefusal("Face readback is not JPEG")
            photo_hash = hashlib.sha256(photo).hexdigest()
        # Preserve every unmanaged native field, including Valid.enable/timeType,
        # doorRight/RightPlan, credentials and security flags. Only known volatile
        # counters/URLs and the independently represented mutation fields are out.
        protected = {k: v for k, v in person.items() if k not in {
            "employeeNo", "name", "userType", "faceURL", "numOfFace", "openDoorTime", "lastAuthenticateTime"}}
        return {**empty, "present": True, "full_name": person["name"], "user_type": person["userType"],
            "policy": {"validity": {"enabled": valid["enable"], "begin": begin.isoformat(), "end": end.isoformat()}, "right_plans": plans},
            "photo_sha256": photo_hash, "face_count": face_count, "card_count": int(person.get("numOfCard", 0)),
            "fingerprint_count": int(person.get("numOfFP", 0)), "other_fields_hash": digest(protected),
            "local_ui_right": person.get("localUIRight"), "double_lock_right": person.get("doubleLockRight")}
