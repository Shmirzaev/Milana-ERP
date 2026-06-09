from fastapi import APIRouter

from app.api.routes import (
    auth, admin, partners, catalog, inventory, sales, planning, production,
    bundles, packages, finished_goods, shipments, waste, finance, dashboards, hr, barcode,
    tasks, notifications, sewing_flows, process_tracking, production_extra, inbox, search, settings,
    cutting_passports,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(partners.router)
api_router.include_router(catalog.router)
api_router.include_router(inventory.router)
api_router.include_router(sales.router)
api_router.include_router(planning.router)
api_router.include_router(production.router)
api_router.include_router(bundles.router)
api_router.include_router(packages.router)
api_router.include_router(finished_goods.router)
api_router.include_router(shipments.router)
api_router.include_router(waste.router)
api_router.include_router(finance.router)
api_router.include_router(dashboards.router)
api_router.include_router(hr.router)
api_router.include_router(barcode.router)
api_router.include_router(tasks.router)
api_router.include_router(notifications.router)
api_router.include_router(sewing_flows.router)
api_router.include_router(process_tracking.router)
api_router.include_router(production_extra.router)
api_router.include_router(inbox.router)
api_router.include_router(search.router)
api_router.include_router(settings.router)
api_router.include_router(cutting_passports.router)
