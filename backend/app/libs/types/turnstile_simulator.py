from typing import TypedDict


class SimulatorEvidence(TypedDict):
    revision: int
    payload_hash: str
    full_name: str
    external_person_id: str
    photo_sha256: str
