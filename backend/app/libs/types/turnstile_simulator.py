from typing import TypedDict, Literal
from app.libs.enums.turnstile import GateAction


class SimulatorEvidence(TypedDict):
    revision: int
    payload_hash: str
    full_name: str
    external_person_id: str
    photo_sha256: str


class SimulatorRevocationEvidence(TypedDict):
    action: Literal[GateAction.REVOKE]
    revision: int
    payload_hash: str
    external_person_id: str
    present: Literal[False]


SimulatorReadback = SimulatorEvidence | SimulatorRevocationEvidence
