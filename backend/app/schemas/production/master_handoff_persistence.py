"""Rename an existing physical flow without changing evidence references."""
from app.schemas import SewingFlow
from sqlalchemy.orm import Session, object_session


def rename_current_master_flow(db: Session, flow: SewingFlow, *, name: str) -> None:
    if object_session(flow) is not db:
        raise ValueError("Flow must belong to the supplied Session")
    flow.name = name
