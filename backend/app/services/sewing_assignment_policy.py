from fastapi import HTTPException


def validate_assignment_progress(quantity: int, completed_qty: int) -> None:
    """Keep recorded sewing output within its assignment's quantity envelope."""
    if quantity <= 0 or completed_qty < 0 or completed_qty > quantity:
        raise HTTPException(409, "Sewing assignment progress must be between zero and assigned quantity")
