// Mirrors the backend create-only CollectionStatus contract.
export enum CollectionStatus {
  DRAFT = "draft",
  APPROVED = "approved",
  ARCHIVED = "archived",
}

export type CollectionCreateIn = {
  brand_id: number;
  name: string;
  season?: string | null;
  year: number;
  description?: string | null;
  status?: CollectionStatus;
};

export type CollectionCreateOut = {
  id: number;
  brand_id: number;
  name: string;
  season: string | null;
  year: number;
  description: string | null;
  status: CollectionStatus;
};
