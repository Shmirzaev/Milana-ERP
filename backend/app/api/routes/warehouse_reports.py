"""Warehouse read-only reports use existing warehouse permissions."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core.deps import DbSession, require_permissions
from app.libs.dto.fulfillment.shipment_report import ShipmentReportOut, ShipmentReportQuery
from app.models.fulfillment.shipment_report_service import shipment_report, shipment_report_workbook

router = APIRouter(prefix="/warehouse-reports", tags=["warehouse-reports"])
WarehouseAccess = Depends(require_permissions("storage.packages", "storage.shipment"))


@router.get("/shipments", response_model=ShipmentReportOut)
def read_shipment_report(db: DbSession, filters: Annotated[ShipmentReportQuery, Query()], _=WarehouseAccess):
    return shipment_report(db, filters)


@router.get("/shipments.xlsx")
def export_shipment_report(db: DbSession, filters: Annotated[ShipmentReportQuery, Query()],
                           _=WarehouseAccess):
    return Response(shipment_report_workbook(db, filters, filters.lang),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="warehouse-shipments.xlsx"'})
