/**
 * The canonical purchase request status vocabulary.
 *
 * These are the stored `purchase_requests.status` strings the API sends. The
 * API owns the vocabulary and declares it on `PurchaseRequestOut`, so the page
 * consumes this enum directly as its declared contract.
 */
export enum PurchaseRequestStatus {
  DRAFT = "draft",
  PENDING_APPROVAL = "pending_approval",
  APPROVED = "approved",
  REJECTED = "rejected",
  CONVERTED = "converted",
}
