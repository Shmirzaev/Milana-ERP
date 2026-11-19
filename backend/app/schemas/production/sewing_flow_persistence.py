"""Sewing-flow state writes in the caller's transaction."""

from sqlalchemy.orm import Session

from app.schemas.production.sewing_flow import SewingFlow


def set_sewing_flow_active(db: Session, flow: SewingFlow, active: bool) -> None:
    flow.is_active = active
