"""Internal contracts for the sales-order header edit.

The HTTP request stays in `libs/dto/sales/`. This module carries the internal
shape between the Sales service and the Sales schema persistence operation, so
neither side passes an unstructured dictionary around.

Key presence is the supplied/not-supplied signal. An absent key leaves the
stored column untouched; a present key holding null clears it.
"""
from datetime import datetime
from typing import NotRequired, TypedDict


class StoredSalesAttachment(TypedDict):
    """One stored sales-order attachment.

    The stored path never carries a signature; the signed URL is produced on
    the way out.
    """
    file_url: str
    file_name: NotRequired[str]
    content_type: NotRequired[str]


class SalesOrderHeaderChanges(TypedDict, total=False):
    """The header fields one sales-order edit supplies.

    `status` is deliberately absent: workflow status is never written by a
    general edit, so it has no key here.
    """
    customer_id: int | None
    deadline: datetime | None
    printing_instructions: str | None
    printing_attachments: list[StoredSalesAttachment] | None
    notes: str | None
