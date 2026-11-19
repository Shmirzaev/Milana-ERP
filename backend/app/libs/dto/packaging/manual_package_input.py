"""Manual Packaging shares quantity validation, never warehouse placement input."""
from app.libs.dto.fulfillment.package_workflows import ManualPackageReceiptIn
from app.libs.enums.packaging import PackagingDepartment


class ManualPackageCreateIn(ManualPackageReceiptIn):
    packaging_department_code: PackagingDepartment = PackagingDepartment.MILANA
    warehouse_id: None = None
    storage_cell: None = None
    storage_shelf: None = None
