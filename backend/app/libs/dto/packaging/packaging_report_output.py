from pydantic import BaseModel


class PackagingReportRow(BaseModel):
    row_key: str
    date: str
    passport: str | None = None
    order_no: str | None = None
    batch: str | None = None
    brand: str | None = None
    model_no: str | None = None
    variant_no: str | None = None
    category: str | None = None
    image_url: str | None = None
    color: str | None = None
    sizes: str | None = None
    standards: str | None = None
    package_count: int | None = None
    quantity: int | None = None
    two_piece_quantity: int | None = None
    first_sort: int | None = None
    second_sort: int | None = None
    cutting_defects: int | None = None
    planned_quantity: int | None = None
    packed_quantity: int | None = None
    damaged_quantity: int | None = None
    shortage: int | None = None
    balance: int | None = None
    notes: str | None = None


class PackagingReportSummary(BaseModel):
    package_count: int | None = None
    quantity: int | None = None
    two_piece_quantity: int | None = None
    first_sort: int | None = None
    second_sort: int | None = None
    cutting_defects: int | None = None
    planned_quantity: int | None = None
    packed_quantity: int | None = None
    damaged_quantity: int | None = None
    shortage: int | None = None
    balance: int | None = None


class PackagingReportPage(BaseModel):
    rows: list[PackagingReportRow]
    total: int
    offset: int
    limit: int
    has_more: bool
    summary: PackagingReportSummary
