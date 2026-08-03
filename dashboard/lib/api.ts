import type {
  ApiResponse,
  ApiResponseMeta,
  CommercialSummaryRead,
  ConfirmationListParams,
  ConfirmationRead,
  CrawlJobCreate,
  CrawlJobListParams,
  CrawlJobRead,
  CrawlRunListParams,
  CrawlRunRead,
  DiscoveryBulkReview,
  DiscoveryCandidateListParams,
  DiscoveryCandidateRead,
  DiscoveryReview,
  DiscoveryRunRead,
  DiscoverySourceRead,
  HealthRead,
  LaunchChecklistItemRead,
  LaunchChecklistUpdate,
  ObservationRead,
  OperationsStatusRead,
  OfferListParams,
  OfferRead,
  Page,
  PageParams,
  PaymentCreate,
  PaymentRead,
  PaymentRecordRead,
  ProblemDetails,
  ProductActivation,
  ProductCreate,
  ProductListParams,
  ProductPatch,
  ProductRead,
  ProductVariant,
  RuntimePolicyPatch,
  RuntimePolicyRead,
  StoreRead,
  SubscriberCreate,
  SubscriberListParams,
  SubscriberPatch,
  SubscriberRead,
  TelegramDistributionStatusRead,
  TelegramTestRead,
  UUID,
} from "./types";

export type FetchImplementation = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface ApiClientOptions {
  baseUrl: string;
  token?: string;
  fetch?: FetchImplementation;
  onUnauthorized?: () => void;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: HeadersInit;
  signal?: AbortSignal;
}

export interface ProductWriteOptions {
  etag: string;
  signal?: AbortSignal;
}

export interface CreateCrawlJobOptions {
  idempotencyKey: string;
  signal?: AbortSignal;
}

export interface UpdateSettingsOptions {
  etag: string;
  idempotencyKey?: string;
  changeReason?: string;
  signal?: AbortSignal;
}

export interface SubscriberWriteOptions {
  etag: string;
  signal?: AbortSignal;
}

export interface RecordPaymentOptions {
  idempotencyKey: string;
  signal?: AbortSignal;
}

function normalizeBaseUrl(rawBaseUrl: string): string {
  const trimmed = rawBaseUrl.trim();
  if (!trimmed) {
    throw new TypeError("La URL de la API es obligatoria.");
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new TypeError("La URL de la API no es válida.");
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new TypeError("La API debe usar el protocolo http o https.");
  }
  if (parsed.username || parsed.password) {
    throw new TypeError("La URL de la API no debe incluir credenciales.");
  }

  parsed.hash = "";
  parsed.search = "";
  parsed.pathname = parsed.pathname.replace(/\/+$/, "");
  return parsed.toString().replace(/\/$/, "");
}

function appendQuery(
  path: string,
  params: object,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params) as Array<
    [string, unknown]
  >) {
    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      query.set(key, String(value));
    }
  }
  const encoded = query.toString();
  return encoded ? `${path}?${encoded}` : path;
}

function responseMeta(response: Response): ApiResponseMeta {
  return {
    etag: response.headers.get("ETag"),
    location: response.headers.get("Location"),
    requestId: response.headers.get("X-Request-ID"),
    idempotentReplay:
      response.headers.get("X-Idempotent-Replay")?.toLowerCase() === "true",
  };
}

function isProblemDetails(value: unknown): value is ProblemDetails {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.type === "string" &&
    typeof candidate.title === "string" &&
    typeof candidate.status === "number" &&
    typeof candidate.detail === "string" &&
    typeof candidate.instance === "string" &&
    typeof candidate.request_id === "string"
  );
}

async function readErrorBody(response: Response): Promise<ProblemDetails | null> {
  const contentType = response.headers.get("Content-Type") ?? "";
  if (!contentType.includes("json")) {
    return null;
  }

  try {
    const value: unknown = await response.json();
    return isProblemDetails(value) ? value : null;
  } catch {
    return null;
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly statusText: string;
  readonly method: string;
  readonly url: string;
  readonly problem: ProblemDetails | null;
  readonly requestId: string | null;

  constructor(options: {
    status: number;
    statusText: string;
    method: string;
    url: string;
    problem: ProblemDetails | null;
    requestId: string | null;
  }) {
    const message =
      options.problem?.detail ||
      `La API respondió ${options.status} ${options.statusText}.`;
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.statusText = options.statusText;
    this.method = options.method;
    this.url = options.url;
    this.problem = options.problem;
    this.requestId = options.problem?.request_id ?? options.requestId;
  }

  get isUnauthorized(): boolean {
    return this.status === 401 || this.status === 403;
  }

  get isStaleRevision(): boolean {
    return this.status === 412;
  }

  get isValidationError(): boolean {
    return this.status === 422;
  }
}

export class ApiNetworkError extends Error {
  readonly cause: unknown;
  readonly method: string;
  readonly url: string;

  constructor(options: {
    method: string;
    url: string;
    cause: unknown;
  }) {
    super("No se pudo conectar con la API.");
    this.name = "ApiNetworkError";
    this.method = options.method;
    this.url = options.url;
    this.cause = options.cause;
  }
}

/**
 * Browser-safe client for the Phase 4A API.
 *
 * The bearer token lives only on this instance. The class never reads from or
 * writes to localStorage, sessionStorage, cookies, or environment variables.
 */
export class ApiClient {
  readonly baseUrl: string;
  private token: string;
  private readonly fetchImplementation: FetchImplementation;
  private unauthorizedHandler?: () => void;

  constructor(options: ApiClientOptions) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl);
    this.token = options.token?.trim() ?? "";
    this.fetchImplementation = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.unauthorizedHandler = options.onUnauthorized;
  }

  setToken(token: string): void {
    this.token = token.trim();
  }

  clearToken(): void {
    this.token = "";
  }

  setUnauthorizedHandler(handler?: () => void): void {
    this.unauthorizedHandler = handler;
  }

  async healthReady(signal?: AbortSignal): Promise<ApiResponse<HealthRead>> {
    return this.request<HealthRead>("/health/ready", { signal });
  }

  async getOperationsStatus(
    signal?: AbortSignal,
  ): Promise<ApiResponse<OperationsStatusRead>> {
    return this.request<OperationsStatusRead>("/api/v1/operations/status", {
      signal,
    });
  }

  async listStores(signal?: AbortSignal): Promise<ApiResponse<StoreRead[]>> {
    return this.request<StoreRead[]>("/api/v1/stores", { signal });
  }

  async listProducts(
    params: ProductListParams = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<Page<ProductRead>>> {
    return this.request<Page<ProductRead>>(
      appendQuery("/api/v1/products", params),
      { signal },
    );
  }

  async createProduct(
    payload: ProductCreate,
    signal?: AbortSignal,
  ): Promise<ApiResponse<ProductRead>> {
    return this.request<ProductRead>("/api/v1/products", {
      method: "POST",
      body: payload,
      signal,
    });
  }

  async getProduct(
    productId: UUID,
    signal?: AbortSignal,
  ): Promise<ApiResponse<ProductRead>> {
    return this.request<ProductRead>(
      `/api/v1/products/${encodeURIComponent(productId)}`,
      { signal },
    );
  }

  async updateProduct(
    productId: UUID,
    payload: ProductPatch,
    options: ProductWriteOptions,
  ): Promise<ApiResponse<ProductRead>> {
    return this.request<ProductRead>(
      `/api/v1/products/${encodeURIComponent(productId)}`,
      {
        method: "PATCH",
        body: payload,
        headers: { "If-Match": options.etag },
        signal: options.signal,
      },
    );
  }

  async archiveProduct(
    productId: UUID,
    options: ProductWriteOptions,
  ): Promise<ApiResponse<null>> {
    return this.request<null>(
      `/api/v1/products/${encodeURIComponent(productId)}`,
      {
        method: "DELETE",
        headers: { "If-Match": options.etag },
        signal: options.signal,
      },
    );
  }

  async setProductActivation(
    productId: UUID,
    payload: ProductActivation,
    options: ProductWriteOptions,
  ): Promise<ApiResponse<ProductRead>> {
    return this.request<ProductRead>(
      `/api/v1/products/${encodeURIComponent(productId)}/activation`,
      {
        method: "PUT",
        body: payload,
        headers: { "If-Match": options.etag },
        signal: options.signal,
      },
    );
  }

  async setProductVariant(
    productId: UUID,
    payload: ProductVariant,
    options: ProductWriteOptions,
  ): Promise<ApiResponse<ProductRead>> {
    return this.request<ProductRead>(
      `/api/v1/products/${encodeURIComponent(productId)}/variant`,
      {
        method: "PUT",
        body: payload,
        headers: { "If-Match": options.etag },
        signal: options.signal,
      },
    );
  }

  async clearProductVariant(
    productId: UUID,
    options: ProductWriteOptions,
  ): Promise<ApiResponse<ProductRead>> {
    return this.request<ProductRead>(
      `/api/v1/products/${encodeURIComponent(productId)}/variant`,
      {
        method: "DELETE",
        headers: { "If-Match": options.etag },
        signal: options.signal,
      },
    );
  }

  async listProductObservations(
    productId: UUID,
    params: PageParams = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<Page<ObservationRead>>> {
    const path = `/api/v1/products/${encodeURIComponent(productId)}/observations`;
    return this.request<Page<ObservationRead>>(appendQuery(path, params), {
      signal,
    });
  }

  async listObservations(
    productId: UUID,
    params: PageParams = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<Page<ObservationRead>>> {
    return this.request<Page<ObservationRead>>(
      appendQuery("/api/v1/observations", {
        product_id: productId,
        ...params,
      }),
      { signal },
    );
  }

  async listOffers(
    params: OfferListParams = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<Page<OfferRead>>> {
    return this.request<Page<OfferRead>>(
      appendQuery("/api/v1/offers", params),
      { signal },
    );
  }

  async listConfirmations(
    params: ConfirmationListParams = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<Page<ConfirmationRead>>> {
    return this.request<Page<ConfirmationRead>>(
      appendQuery("/api/v1/confirmations", params),
      { signal },
    );
  }

  async listCrawlRuns(
    params: CrawlRunListParams = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<Page<CrawlRunRead>>> {
    return this.request<Page<CrawlRunRead>>(
      appendQuery("/api/v1/crawl-runs", params),
      { signal },
    );
  }

  async createCrawlJob(
    payload: CrawlJobCreate,
    options: CreateCrawlJobOptions,
  ): Promise<ApiResponse<CrawlJobRead>> {
    return this.request<CrawlJobRead>("/api/v1/crawl-jobs", {
      method: "POST",
      body: payload,
      headers: { "Idempotency-Key": options.idempotencyKey },
      signal: options.signal,
    });
  }

  async listCrawlJobs(
    params: CrawlJobListParams = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<Page<CrawlJobRead>>> {
    return this.request<Page<CrawlJobRead>>(
      appendQuery("/api/v1/crawl-jobs", params),
      { signal },
    );
  }

  async getCrawlJob(
    jobId: UUID,
    signal?: AbortSignal,
  ): Promise<ApiResponse<CrawlJobRead>> {
    return this.request<CrawlJobRead>(
      `/api/v1/crawl-jobs/${encodeURIComponent(jobId)}`,
      { signal },
    );
  }

  async cancelCrawlJob(
    jobId: UUID,
    signal?: AbortSignal,
  ): Promise<ApiResponse<CrawlJobRead>> {
    return this.request<CrawlJobRead>(
      `/api/v1/crawl-jobs/${encodeURIComponent(jobId)}/cancel`,
      { method: "POST", signal },
    );
  }

  async listDiscoverySources(
    signal?: AbortSignal,
  ): Promise<ApiResponse<DiscoverySourceRead[]>> {
    return this.request<DiscoverySourceRead[]>("/api/v1/discovery/sources", {
      signal,
    });
  }

  async scheduleDiscoverySource(
    sourceId: UUID,
    signal?: AbortSignal,
  ): Promise<ApiResponse<DiscoverySourceRead>> {
    return this.request<DiscoverySourceRead>(
      `/api/v1/discovery/sources/${encodeURIComponent(sourceId)}/run`,
      { method: "POST", signal },
    );
  }

  async listDiscoveryCandidates(
    params: DiscoveryCandidateListParams = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<Page<DiscoveryCandidateRead>>> {
    return this.request<Page<DiscoveryCandidateRead>>(
      appendQuery("/api/v1/discovery/candidates", params),
      { signal },
    );
  }

  async listDiscoveryRuns(
    params: { limit?: number; store_slug?: string } = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<DiscoveryRunRead[]>> {
    return this.request<DiscoveryRunRead[]>(
      appendQuery("/api/v1/discovery/runs", params),
      { signal },
    );
  }

  async reviewDiscoveryCandidate(
    candidateId: UUID,
    payload: DiscoveryReview,
    signal?: AbortSignal,
  ): Promise<ApiResponse<DiscoveryCandidateRead>> {
    return this.request<DiscoveryCandidateRead>(
      `/api/v1/discovery/candidates/${encodeURIComponent(candidateId)}/review`,
      { method: "POST", body: payload, signal },
    );
  }

  async bulkReviewDiscoveryCandidates(
    payload: DiscoveryBulkReview,
    signal?: AbortSignal,
  ): Promise<ApiResponse<DiscoveryCandidateRead[]>> {
    return this.request<DiscoveryCandidateRead[]>(
      "/api/v1/discovery/candidates/review",
      { method: "POST", body: payload, signal },
    );
  }

  async getTelegramDistribution(
    signal?: AbortSignal,
  ): Promise<ApiResponse<TelegramDistributionStatusRead>> {
    return this.request<TelegramDistributionStatusRead>(
      "/api/v1/distribution/telegram",
      { signal },
    );
  }

  async testTelegramDistribution(
    destination: "telegram_free" | "telegram_vip" = "telegram_free",
    signal?: AbortSignal,
  ): Promise<ApiResponse<TelegramTestRead>> {
    return this.request<TelegramTestRead>(
      appendQuery("/api/v1/distribution/telegram/test", { destination }),
      { method: "POST", signal },
    );
  }

  async getCommercialSummary(
    signal?: AbortSignal,
  ): Promise<ApiResponse<CommercialSummaryRead>> {
    return this.request<CommercialSummaryRead>("/api/v1/commercial/summary", {
      signal,
    });
  }

  async getLaunchChecklist(
    signal?: AbortSignal,
  ): Promise<ApiResponse<LaunchChecklistItemRead[]>> {
    return this.request<LaunchChecklistItemRead[]>(
      "/api/v1/commercial/checklist",
      { signal },
    );
  }

  async updateLaunchChecklistItem(
    itemKey: string,
    payload: LaunchChecklistUpdate,
    signal?: AbortSignal,
  ): Promise<ApiResponse<LaunchChecklistItemRead>> {
    return this.request<LaunchChecklistItemRead>(
      `/api/v1/commercial/checklist/${encodeURIComponent(itemKey)}`,
      { method: "PUT", body: payload, signal },
    );
  }

  async listSubscribers(
    params: SubscriberListParams = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<Page<SubscriberRead>>> {
    return this.request<Page<SubscriberRead>>(
      appendQuery("/api/v1/subscribers", params),
      { signal },
    );
  }

  async createSubscriber(
    payload: SubscriberCreate,
    signal?: AbortSignal,
  ): Promise<ApiResponse<SubscriberRead>> {
    return this.request<SubscriberRead>("/api/v1/subscribers", {
      method: "POST",
      body: payload,
      signal,
    });
  }

  async updateSubscriber(
    subscriberId: UUID,
    payload: SubscriberPatch,
    options: SubscriberWriteOptions,
  ): Promise<ApiResponse<SubscriberRead>> {
    return this.request<SubscriberRead>(
      `/api/v1/subscribers/${encodeURIComponent(subscriberId)}`,
      {
        method: "PATCH",
        body: payload,
        headers: { "If-Match": options.etag },
        signal: options.signal,
      },
    );
  }

  async listSubscriberPayments(
    subscriberId: UUID,
    signal?: AbortSignal,
  ): Promise<ApiResponse<PaymentRead[]>> {
    return this.request<PaymentRead[]>(
      `/api/v1/subscribers/${encodeURIComponent(subscriberId)}/payments`,
      { signal },
    );
  }

  async recordSubscriberPayment(
    subscriberId: UUID,
    payload: PaymentCreate,
    options: RecordPaymentOptions,
  ): Promise<ApiResponse<PaymentRecordRead>> {
    return this.request<PaymentRecordRead>(
      `/api/v1/subscribers/${encodeURIComponent(subscriberId)}/payments`,
      {
        method: "POST",
        body: payload,
        headers: { "Idempotency-Key": options.idempotencyKey },
        signal: options.signal,
      },
    );
  }

  async getSettings(
    signal?: AbortSignal,
  ): Promise<ApiResponse<RuntimePolicyRead>> {
    return this.request<RuntimePolicyRead>("/api/v1/settings", { signal });
  }

  async updateSettings(
    payload: RuntimePolicyPatch,
    options: UpdateSettingsOptions,
  ): Promise<ApiResponse<RuntimePolicyRead>> {
    const headers = new Headers({ "If-Match": options.etag });
    if (options.idempotencyKey) {
      headers.set("Idempotency-Key", options.idempotencyKey);
    }
    if (options.changeReason) {
      headers.set("X-Change-Reason", options.changeReason);
    }

    return this.request<RuntimePolicyRead>("/api/v1/settings", {
      method: "PATCH",
      body: payload,
      headers,
      signal: options.signal,
    });
  }

  private async request<T>(
    path: string,
    options: RequestOptions = {},
  ): Promise<ApiResponse<T>> {
    const method = options.method ?? "GET";
    const url = `${this.baseUrl}${path}`;
    const headers = new Headers(options.headers);
    headers.set("Accept", "application/json, application/problem+json");
    if (this.token && path.startsWith("/api/")) {
      headers.set("Authorization", `Bearer ${this.token}`);
    }
    if (options.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }

    let response: Response;
    try {
      response = await this.fetchImplementation(url, {
        method,
        headers,
        body:
          options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: options.signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw error;
      }
      throw new ApiNetworkError({ method, url, cause: error });
    }

    if (!response.ok) {
      const problem = await readErrorBody(response);
      if (response.status === 401 || response.status === 403) {
        this.clearToken();
        this.unauthorizedHandler?.();
      }
      throw new ApiError({
        status: response.status,
        statusText: response.statusText,
        method,
        url,
        problem,
        requestId: response.headers.get("X-Request-ID"),
      });
    }

    const meta = responseMeta(response);
    if (response.status === 204) {
      return { data: null as T, meta };
    }

    return {
      data: (await response.json()) as T,
      meta,
    };
  }
}
