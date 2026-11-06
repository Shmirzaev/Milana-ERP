/** Controlled creation vocabulary; historical saved rows remain open strings. */
export enum ForecastRecommendationType {
  BRANDED_STOCK_PRODUCTION = "branded_stock_production",
  ITEM_REORDER = "item_reorder",
}

export enum ForecastRecommendationStatus {
  OPEN = "open",
  ACCEPTED = "accepted",
  DISMISSED = "dismissed",
  CONVERTED = "converted",
}

/** Known generated fields plus extensible metadata retained verbatim on save. */
export interface ForecastSuggestion extends Record<string, unknown> {
  recommendation_type: ForecastRecommendationType;
  model_id?: number | null;
  item_id?: number | null;
  brand_id?: number | null;
  collection_id?: number | null;
  model_code?: string | null;
  model_name?: string | null;
  item_sku?: string | null;
  item_name?: string | null;
  brand_name?: string | null;
  category?: string | null;
  color?: string | null;
  size?: string | null;
  suggested_quantity: number;
  unit?: string | null;
  confidence?: string | null;
  reason?: string | null;
  projected_demand?: number;
  available_quantity?: number;
  reserved_quantity?: number;
  reorder_level?: number;
  planned_bom_demand?: number;
}

export interface ForecastRecommendationInput {
  recommendation_type: ForecastRecommendationType;
  model_id: number | null;
  item_id: number | null;
  brand_id: number | null;
  collection_id: number | null;
  color: string | null;
  size: string | null;
  suggested_quantity: number;
  unit: string;
  confidence: string | null;
  reason: string | null;
  source_json: Record<string, unknown>;
}

export interface ForecastRecommendationLegacyRow {
  id: number;
  recommendation_type: string;
  status: string;
  color?: string | null;
  size?: string | null;
  suggested_quantity: number;
  unit?: string | null;
  confidence?: string | null;
  reason?: string | null;
  source_json?: Record<string, unknown> | null;
  created_at: string;
}

export interface ForecastRecommendationCreated extends ForecastRecommendationLegacyRow {
  recommendation_type: ForecastRecommendationType;
  status: ForecastRecommendationStatus;
}

export interface ForecastDashboard {
  branded_stock_suggestions: ForecastSuggestion[];
  item_reorder_suggestions: ForecastSuggestion[];
  demand_trend: { week_start: string; quantity: number }[];
  cards: Record<string, number>;
  unlinked_bom_count: number;
}

/** Preserve the existing HTTP normalization, including unknown metadata keys. */
export function forecastRecommendationInput(row: ForecastSuggestion): ForecastRecommendationInput {
  return {
    recommendation_type: row.recommendation_type,
    model_id: row.model_id || null,
    item_id: row.item_id || null,
    brand_id: row.brand_id || null,
    collection_id: row.collection_id || null,
    color: row.color || null,
    size: row.size || null,
    suggested_quantity: Number(row.suggested_quantity || 0),
    unit: row.unit || "pcs",
    confidence: row.confidence || null,
    reason: row.reason || null,
    source_json: row,
  };
}
