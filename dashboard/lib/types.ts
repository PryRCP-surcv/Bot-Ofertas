/**
 * TypeScript representation of the Phase 4A administration API.
 *
 * Field names intentionally follow the API's snake_case JSON contract. This
 * keeps requests auditable and avoids a second mapping layer in the dashboard.
 */

export type UUID = string;
export type ISODateTime = string;
export type DecimalValue = string | number;

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export interface JsonObject {
  [key: string]: JsonValue;
}

export interface Page<T> {
  items: T[];
  limit: number;
  has_more: boolean;
  next_cursor: string | null;
}

export interface PageParams {
  cursor?: string;
  limit?: number;
}

export interface HealthRead {
  status: string;
  service: string;
  database: string | null;
}

export type WorkerState = "running" | "stale" | "stopped" | "unknown";

/**
 * Live operational contract exposed by GET /api/v1/operations/status.
 *
 * Timestamps and cycle details are nullable because a newly installed worker
 * may not have emitted its first heartbeat or completed a cycle yet. Unknown
 * fields returned by future API versions are intentionally harmless: this
 * dashboard only reads the stable fields declared here.
 */
export interface WorkerOperationsRead {
  state: WorkerState;
  instance_id: string | null;
  started_at: ISODateTime | null;
  last_heartbeat_at: ISODateTime | null;
  heartbeat_age_seconds: number | null;
  stale_after_seconds: number | null;
  last_cycle_started_at: ISODateTime | null;
  last_cycle_finished_at: ISODateTime | null;
  last_cycle_status: string | null;
  last_error: string | null;
  message?: string | null;
}

export interface QueueOperationsRead {
  queued: number;
  running: number;
  retrying: number;
}

export interface OperationsStatusRead {
  worker: WorkerOperationsRead;
  queue: QueueOperationsRead;
  checked_at: ISODateTime;
}

export interface StoreRead {
  slug: string;
  display_name: string;
  hosts: string[];
  enabled: boolean;
  minimum_interval_minutes: number;
  max_targets_per_run: number;
  requires_explicit_product_url: boolean;
  notes: string;
  health: string;
  paused_until: ISODateTime | null;
  pause_reason: string | null;
  consecutive_blocks: number;
  tracked_products: number;
  active_products: number;
  last_run_id: UUID | null;
  last_run_status: string | null;
  last_run_started_at: ISODateTime | null;
  last_run_finished_at: ISODateTime | null;
}

export interface ProductCreate {
  url: string;
  label: string;
  expected_brand?: string | null;
  expected_model?: string | null;
  expected_variant?: Record<string, string>;
  expected_is_accessory?: boolean;
  check_interval_minutes?: number;
  active?: boolean;
}

export interface ProductPatch {
  label?: string;
  expected_brand?: string | null;
  expected_model?: string | null;
  expected_is_accessory?: boolean;
  check_interval_minutes?: number;
}

export interface ProductRead {
  id: UUID;
  store_slug: string;
  source_url: string;
  label: string;
  expected_brand: string | null;
  expected_model: string | null;
  expected_variant: Record<string, string>;
  expected_is_accessory: boolean;
  active: boolean;
  version: number;
  archived_at: ISODateTime | null;
  check_interval_minutes: number;
  last_checked_at: ISODateTime | null;
  last_success_at: ISODateTime | null;
  consecutive_failures: number;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface ProductActivation {
  active: boolean;
}

export interface ProductVariant {
  expected_variant: Record<string, string>;
}

export interface ProductListParams extends PageParams {
  store_slug?: string;
  active?: boolean;
  archived?: boolean;
  search?: string;
}

export interface ObservationRead {
  id: number;
  tracked_product_id: UUID | null;
  run_id: UUID;
  store_slug: string;
  source_url: string;
  external_product_id: string;
  sku: string;
  seller_id: string;
  seller_name: string;
  title: string;
  brand: string | null;
  model: string | null;
  variant: Record<string, string>;
  condition: string;
  currency: string;
  price: DecimalValue | null;
  list_price: DecimalValue | null;
  availability: string;
  available_quantity: number | null;
  is_marketplace: boolean;
  installments: JsonObject[];
  quality_flags: string[];
  observed_at: ISODateTime;
}

export type DealClassification =
  | "none"
  | "good_deal"
  | "exceptional_deal"
  | "possible_price_error";

export type ConfidenceLevel = "none" | "low" | "medium" | "high";

export type ConfirmationStatus =
  | "not_applicable"
  | "not_required"
  | "awaiting"
  | "confirmed"
  | "expired"
  | "replaced";

export type NotificationStatus =
  | "not_applicable"
  | "awaiting_confirmation"
  | "pending"
  | "suppressed"
  | "retrying"
  | "sent"
  | "failed"
  | "superseded";

export interface OfferRead {
  id: number;
  observation_id: number;
  tracked_product_id: UUID | null;
  product_label: string;
  title: string;
  store_slug: string;
  source_url: string;
  detector_version: string;
  policy_fingerprint: string;
  config_revision_id: number | null;
  classification: DealClassification;
  eligible: boolean;
  score: number;
  confidence_score: number;
  confidence_level: ConfidenceLevel;
  currency: string;
  current_price: DecimalValue | null;
  reference_price: DecimalValue | null;
  discount_percent: DecimalValue | null;
  primary_signal_kind: string | null;
  signals: JsonObject;
  notification_status: NotificationStatus;
  confirmation_status: ConfirmationStatus;
  confirmation_count: number;
  reasons: string[];
  rejection_reasons: string[];
  quality_flags: string[];
  detected_at: ISODateTime;
}

export type OfferState = "active" | "awaiting" | "history";

export interface OfferListParams extends PageParams {
  classification?: DealClassification;
  store_slug?: string;
  notification_status?: NotificationStatus;
  include_rejected?: boolean;
  state?: OfferState;
}

export interface ConfirmationRead {
  offer_key: string;
  tracked_product_id: UUID | null;
  product_label: string | null;
  candidate_detection_id: number | null;
  candidate_classification: Exclude<DealClassification, "none">;
  candidate_price: DecimalValue;
  confirmation_count: number;
  first_seen_at: ISODateTime;
  last_seen_at: ISODateTime;
  expires_at: ISODateTime;
}

export interface ConfirmationListParams extends PageParams {
  active_only?: boolean;
}

export type CrawlRunStatus =
  | "running"
  | "succeeded"
  | "partial"
  | "failed"
  | "cancelled";

export interface CrawlRunRead {
  id: UUID;
  store_slug: string;
  spider_name: string;
  status: CrawlRunStatus;
  requested_url_count: number;
  observation_count: number;
  error_count: number;
  error_summary: string | null;
  started_at: ISODateTime;
  finished_at: ISODateTime | null;
}

export interface CrawlRunListParams extends PageParams {
  store_slug?: string;
  status?: CrawlRunStatus;
}

export type CrawlJobStatus =
  | "queued"
  | "running"
  | "retrying"
  | "succeeded"
  | "partial"
  | "failed"
  | "cancelled";

export type CrawlJobItemStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped"
  | "cancelled";

export interface CrawlJobCreate {
  product_ids: UUID[];
}

export interface CrawlJobItemRead {
  id: number;
  tracked_product_id: UUID;
  crawl_run_id: UUID | null;
  store_slug: string;
  source_url: string;
  label: string;
  status: CrawlJobItemStatus;
  attempt_count: number;
  started_at: ISODateTime | null;
  finished_at: ISODateTime | null;
  last_error_code: string | null;
  last_error: string | null;
  result: JsonObject;
}

export interface CrawlJobRead {
  id: UUID;
  status: CrawlJobStatus;
  request_source: string;
  requested_by: string;
  request_payload: JsonObject;
  priority: number;
  max_attempts: number;
  attempt_count: number;
  next_attempt_at: ISODateTime;
  config_revision_id: number | null;
  started_at: ISODateTime | null;
  finished_at: ISODateTime | null;
  cancel_requested_at: ISODateTime | null;
  last_error_code: string | null;
  last_error: string | null;
  result: JsonObject;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  items: CrawlJobItemRead[];
}

export interface CrawlJobListParams extends PageParams {
  status?: CrawlJobStatus;
}

export interface RuntimePolicyRead {
  revision_id: number | null;
  policy_fingerprint: string;
  changed_by: string | null;
  change_reason: string | null;
  detector_version: string;
  scheduler_poll_seconds: number;
  detection_history_limit: number;
  detection_history_days: number;
  minimum_history_samples: number;
  equivalent_max_age_hours: number;
  equivalent_limit: number;
  minimum_equivalent_samples: number;
  possible_error_minimum_corroborating_signals: number;
  possible_error_minimum_confidence: number;
  confirmation_required: boolean;
  confirmation_max_age_minutes: number;
  confirmation_price_tolerance_percent: DecimalValue;
  confirmation_confidence_bonus: number;
  minimum_alert_confidence: number;
  good_deal_percent: DecimalValue;
  exceptional_deal_percent: DecimalValue;
  possible_price_error_percent: DecimalValue;
  alert_cooldown_hours: number;
  alert_significant_improvement_percent: DecimalValue;
  notification_lease_seconds: number;
  notification_max_attempts: number;
  notification_retry_base_seconds: number;
  telegram_enabled: boolean;
  telegram_configured: boolean;
  telegram_token_configured: boolean;
  telegram_chat_id_configured: boolean;
}

export interface RuntimePolicyPatch {
  scheduler_poll_seconds?: number;
  detection_history_limit?: number;
  detection_history_days?: number;
  equivalent_max_age_hours?: number;
  equivalent_limit?: number;
  confirmation_required?: boolean;
  confirmation_max_age_minutes?: number;
  confirmation_price_tolerance_percent?: DecimalValue;
  confirmation_confidence_bonus?: number;
  minimum_alert_confidence?: number;
  alert_cooldown_hours?: number;
  alert_significant_improvement_percent?: DecimalValue;
  notification_lease_seconds?: number;
  notification_max_attempts?: number;
  notification_retry_base_seconds?: number;
  telegram_enabled?: boolean;
  minimum_history_samples?: number;
  minimum_equivalent_samples?: number;
  possible_error_minimum_corroborating_signals?: number;
  possible_error_minimum_confidence?: number;
  good_deal_percent?: DecimalValue;
  exceptional_deal_percent?: DecimalValue;
  possible_price_error_percent?: DecimalValue;
}

export interface ProblemDetails {
  [key: string]: unknown;
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
  request_id: string;
  invalid_fields?: string[];
}

export interface ApiResponseMeta {
  etag: string | null;
  location: string | null;
  requestId: string | null;
  idempotentReplay: boolean;
}

export interface ApiResponse<T> {
  data: T;
  meta: ApiResponseMeta;
}
