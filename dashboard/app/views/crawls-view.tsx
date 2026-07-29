"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiClient } from "@/lib/api";
import {
  formatDateTime,
  formatRelativeTime,
  makeIdempotencyKey,
  shortId,
  titleCase,
} from "@/lib/format";
import {
  jobStatusLabels,
  jobTone,
  runStatusLabels,
  workerStateLabels,
  workerStateTones,
} from "@/lib/presentation";
import type {
  CrawlJobRead,
  CrawlRunRead,
  OperationsStatusRead,
  ProductRead,
  StoreRead,
} from "@/lib/types";

import { RadarIcon, SearchIcon } from "../components/icons";
import {
  Button,
  EmptyState,
  LoadingBlock,
  Modal,
  StatusPill,
} from "../components/ui";

interface CrawlData {
  jobs: CrawlJobRead[];
  loadedAt: number;
  products: ProductRead[];
  productsHasMore: boolean;
  runs: CrawlRunRead[];
  stores: StoreRead[];
}

function productIsDue(
  product: ProductRead,
  stores: StoreRead[],
  now: number,
): boolean {
  const store = stores.find((item) => item.slug === product.store_slug);
  if (!store?.enabled) {
    return false;
  }
  if (
    store.paused_until &&
    new Date(store.paused_until).getTime() > now
  ) {
    return false;
  }
  if (!product.last_checked_at) {
    return true;
  }
  const lastCheckedAt = new Date(product.last_checked_at).getTime();
  if (!Number.isFinite(lastCheckedAt)) {
    return true;
  }
  return (
    lastCheckedAt + product.check_interval_minutes * 60_000 <= now
  );
}

export function CrawlsView({
  client,
  onNotify,
  operationsError,
  operationsStatus,
  refreshNonce,
}: {
  client: ApiClient;
  onNotify: (message: string, tone: "success" | "error") => void;
  operationsError: string;
  operationsStatus: OperationsStatusRead | null;
  refreshNonce: number;
}) {
  const [data, setData] = useState<CrawlData | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(
    async (silent = false) => {
      if (!silent) {
        setLoading(true);
      }
      setError("");
      try {
        const [products, jobs, runs, stores] = await Promise.all([
          client.listProducts({ active: true, archived: false, limit: 100 }),
          client.listCrawlJobs({ limit: 25 }),
          client.listCrawlRuns({ limit: 25 }),
          client.listStores(),
        ]);
        setData({
          products: products.data.items,
          productsHasMore: products.data.has_more,
          jobs: jobs.data.items,
          runs: runs.data.items,
          stores: stores.data,
          loadedAt: Date.now(),
        });
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "No se pudo consultar la operación de rastreo.",
        );
      } finally {
        setLoading(false);
      }
    },
    [client],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load, refreshNonce]);

  const hasOpenJobs =
    data?.jobs.some((job) =>
      ["queued", "running", "retrying"].includes(job.status),
    ) ?? false;

  useEffect(() => {
    if (!hasOpenJobs) {
      return;
    }
    const timer = window.setInterval(() => {
      void load(true);
    }, 15_000);
    return () => window.clearInterval(timer);
  }, [hasOpenJobs, load]);

  const visibleProducts = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    if (!normalizedSearch) {
      return data?.products ?? [];
    }
    return (data?.products ?? []).filter((product) =>
      `${product.label} ${product.store_slug} ${product.expected_brand ?? ""} ${product.expected_model ?? ""}`
        .toLowerCase()
        .includes(normalizedSearch),
    );
  }, [data?.products, search]);

  const eligibleProducts = useMemo(
    () =>
      visibleProducts.filter((product) =>
        productIsDue(product, data?.stores ?? [], data?.loadedAt ?? 0),
      ),
    [data?.loadedAt, data?.stores, visibleProducts],
  );

  const allEligibleProducts = useMemo(
    () =>
      (data?.products ?? []).filter((product) =>
        productIsDue(product, data?.stores ?? [], data?.loadedAt ?? 0),
      ),
    [data?.loadedAt, data?.products, data?.stores],
  );

  const selectedProducts = useMemo(
    () =>
      (data?.products ?? []).filter((product) =>
        selected.includes(product.id),
      ),
    [data?.products, selected],
  );

  const selectedByStore = useMemo(() => {
    const counts = new Map<string, number>();
    for (const product of data?.products ?? []) {
      if (selected.includes(product.id)) {
        counts.set(
          product.store_slug,
          (counts.get(product.store_slug) ?? 0) + 1,
        );
      }
    }
    return counts;
  }, [data?.products, selected]);

  const limitViolation = [...selectedByStore.entries()].find(
    ([storeSlug, count]) => {
      const store = data?.stores.find((item) => item.slug === storeSlug);
      return store ? count > store.max_targets_per_run : false;
    },
  );

  function toggleSelection(productId: string) {
    setReviewOpen(false);
    setSelected((current) => {
      if (current.includes(productId)) {
        return current.filter((id) => id !== productId);
      }
      if (current.length >= 20) {
        onNotify("Cada trabajo admite como máximo 20 productos.", "error");
        return current;
      }
      return [...current, productId];
    });
  }

  function quickSelect(products: ProductRead[], selectionLabel: string) {
    const nextSelection: string[] = [];
    const countsByStore = new Map<string, number>();

    for (const product of products) {
      if (nextSelection.length >= 20) {
        break;
      }
      const store = data?.stores.find(
        (item) => item.slug === product.store_slug,
      );
      if (!store?.enabled) {
        continue;
      }
      const currentCount = countsByStore.get(product.store_slug) ?? 0;
      if (currentCount >= store.max_targets_per_run) {
        continue;
      }
      countsByStore.set(product.store_slug, currentCount + 1);
      nextSelection.push(product.id);
    }

    setReviewOpen(false);
    setSelected(nextSelection);
    onNotify(
      nextSelection.length
        ? `${nextSelection.length} ${selectionLabel} seleccionados. Revisa el envío antes de confirmarlo.`
        : `No hay productos ${selectionLabel} disponibles en esta vista.`,
      nextSelection.length ? "success" : "error",
    );
  }

  function requestJobReview() {
    if (!selected.length || limitViolation) {
      return;
    }
    setReviewOpen(true);
  }

  async function createJob() {
    if (!selected.length || limitViolation) {
      return;
    }
    setSubmitting(true);
    try {
      const response = await client.createCrawlJob(
        { product_ids: selected },
        { idempotencyKey: makeIdempotencyKey("panel-crawl") },
      );
      setSelected([]);
      setReviewOpen(false);
      onNotify(
        `Trabajo ${shortId(response.data.id)} enviado a la cola.`,
        "success",
      );
      await load(true);
    } catch (createError) {
      onNotify(
        createError instanceof Error
          ? createError.message
          : "No se pudo crear el trabajo.",
        "error",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelJob(job: CrawlJobRead) {
    try {
      await client.cancelCrawlJob(job.id);
      onNotify("Cancelación solicitada.", "success");
      await load(true);
    } catch (cancelError) {
      onNotify(
        cancelError instanceof Error
          ? cancelError.message
          : "No se pudo cancelar el trabajo.",
        "error",
      );
    }
  }

  if (loading && !data) {
    return <LoadingBlock label="Consultando la cola de rastreo" />;
  }

  if (error && !data) {
    return (
      <EmptyState
        action={<Button onClick={() => void load()}>Reintentar</Button>}
        description={error}
        title="No se pudo consultar el rastreo"
      />
    );
  }

  const jobs = data?.jobs ?? [];
  const runs = data?.runs ?? [];
  const workerState = operationsStatus?.worker.state ?? "unknown";
  const workerTone = operationsError ? "danger" : workerStateTones[workerState];
  const workerLabel = operationsError
    ? "Estado no disponible"
    : operationsStatus
      ? workerStateLabels[workerState]
      : "Consultando trabajador";
  const lastHeartbeat = operationsStatus?.worker.last_heartbeat_at;
  const lastCycle =
    operationsStatus?.worker.last_cycle_finished_at ??
    operationsStatus?.worker.last_cycle_started_at;
  const workerUnavailable =
    Boolean(operationsError) ||
    ["stale", "stopped", "unknown"].includes(workerState);

  return (
    <div className="view-stack">
      {error ? <div className="inline-error">{error}</div> : null}
      <section className="view-heading">
        <div>
          <p className="section-kicker">Cola responsable</p>
          <h2>Solicita una revisión sin saltar límites</h2>
          <p>
            Seleccionar no inicia ninguna consulta. Después revisarás el
            resumen y confirmarás el envío a la cola; el monitor volverá a
            validar intervalos, cuotas, pausas, robots.txt y CAPTCHA.
          </p>
        </div>
      </section>

      <section
        aria-live="polite"
        className={`worker-inline-status worker-inline-status--${workerTone}`}
        role={workerUnavailable ? "alert" : "status"}
      >
        <div>
          <span className="worker-inline-status__dot" aria-hidden="true" />
          <strong>{workerLabel}</strong>
        </div>
        <span>
          Última señal:{" "}
          {lastHeartbeat ? formatRelativeTime(lastHeartbeat) : "sin registro"}
        </span>
        <span>
          Último ciclo: {lastCycle ? formatRelativeTime(lastCycle) : "sin registro"}
          {operationsStatus?.worker.last_cycle_status
            ? ` · ${titleCase(operationsStatus.worker.last_cycle_status)}`
            : ""}
        </span>
        {workerUnavailable ? (
          <small>
            {operationsError ||
              operationsStatus?.worker.last_error ||
              operationsStatus?.worker.message ||
              "Puedes preparar el trabajo, pero permanecerá en cola hasta que el trabajador vuelva a estar activo."}
          </small>
        ) : null}
      </section>

      <section className="crawl-layout">
        <article className="surface crawl-picker">
          <header className="surface__header">
            <div>
              <p className="section-kicker">Nuevo trabajo</p>
              <h2>Selecciona productos</h2>
            </div>
            <span className="selection-count">{selected.length}/20</span>
          </header>
          <div className="crawl-picker__search">
            <SearchIcon />
            <input
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Filtrar productos"
              value={search}
            />
          </div>
          <div className="crawl-picker__quick-actions">
            <Button
              disabled={!eligibleProducts.length}
              onClick={() =>
                quickSelect(eligibleProducts, "pendientes elegibles")
              }
              tone="secondary"
              type="button"
            >
              Elegibles visibles ({eligibleProducts.length})
            </Button>
            <Button
              disabled={!allEligibleProducts.length}
              onClick={() =>
                quickSelect(allEligibleProducts, "activos elegibles")
              }
              tone="ghost"
              type="button"
            >
              Todos los elegibles activos ({allEligibleProducts.length})
            </Button>
            {selected.length ? (
              <button
                className="text-link"
                onClick={() => {
                  setReviewOpen(false);
                  setSelected([]);
                }}
                type="button"
              >
                Limpiar
              </button>
            ) : null}
          </div>
          <p className="crawl-picker__eligibility-note">
            “Elegibles” estima qué productos ya cumplieron su intervalo y no
            tienen una pausa activa. El servidor siempre hace la validación
            definitiva.
          </p>
          <div className="crawl-product-list">
            {visibleProducts.length ? (
              visibleProducts.map((product) => (
                <label key={product.id}>
                  <input
                    checked={selected.includes(product.id)}
                    onChange={() => toggleSelection(product.id)}
                    type="checkbox"
                  />
                  <span>
                    <strong>{product.label}</strong>
                    <small>
                      {titleCase(product.store_slug)} · cada{" "}
                      {product.check_interval_minutes} min
                    </small>
                  </span>
                </label>
              ))
            ) : (
              <p className="list-empty">No hay productos activos que coincidan.</p>
            )}
          </div>
          {data?.productsHasMore ? (
            <p className="form-hint">
              Se muestran los primeros 100 productos activos. Usa la búsqueda
              del catálogo para gestionar el resto.
            </p>
          ) : null}
          {limitViolation ? (
            <div className="form-error">
              La tienda {titleCase(limitViolation[0])} permite como máximo{" "}
              {data?.stores.find((store) => store.slug === limitViolation[0])
                ?.max_targets_per_run ?? "su límite"}{" "}
              productos por trabajo.
            </div>
          ) : null}
          <div className="crawl-picker__footer">
            <div>
              {[...selectedByStore.entries()].map(([slug, count]) => (
                <span key={slug}>
                  {titleCase(slug)}: {count}
                </span>
              ))}
            </div>
            <Button
              disabled={!selected.length || submitting || Boolean(limitViolation)}
              onClick={requestJobReview}
            >
              <RadarIcon />
              Revisar envío
            </Button>
          </div>
        </article>

        <article className="surface job-queue">
          <header className="surface__header">
            <div>
              <p className="section-kicker">Monitor</p>
              <h2>Trabajos recientes</h2>
            </div>
            {hasOpenJobs ? <span className="live-label">Actualización 15 s</span> : null}
          </header>
          {jobs.length ? (
            <div className="job-list">
              {jobs.map((job) => {
                const open = ["queued", "running", "retrying"].includes(job.status);
                const queuedTooLong =
                  job.status === "queued" &&
                  (data?.loadedAt ?? 0) - new Date(job.created_at).getTime() >
                    10 * 60_000;
                return (
                  <details className="job-row" key={job.id}>
                    <summary>
                      <div>
                        <strong>Trabajo {shortId(job.id)}</strong>
                        <span>
                          {job.items.length} producto
                          {job.items.length === 1 ? "" : "s"} ·{" "}
                          {formatRelativeTime(job.created_at)}
                        </span>
                      </div>
                      <StatusPill tone={jobTone(job.status)}>
                        {jobStatusLabels[job.status]}
                      </StatusPill>
                    </summary>
                    <div className="job-row__details">
                      {queuedTooLong ? (
                        <div className="job-warning">
                          Lleva más de 10 minutos en cola. Comprueba que{" "}
                          <code>bot-ofertas run</code> siga ejecutándose.
                        </div>
                      ) : null}
                      <ul>
                        {job.items.map((item) => (
                          <li key={item.id}>
                            <span>
                              <strong>{item.label}</strong>
                              <small>{titleCase(item.store_slug)}</small>
                            </span>
                            <StatusPill tone={jobTone(
                              item.status === "skipped" ? "partial" : item.status,
                            )}>
                              {titleCase(item.status)}
                            </StatusPill>
                          </li>
                        ))}
                      </ul>
                      {job.last_error ? (
                        <p className="inline-error">{job.last_error}</p>
                      ) : null}
                      <div className="job-row__footer">
                        <span>Actualizado {formatDateTime(job.updated_at)}</span>
                        {open ? (
                          <Button
                            onClick={() => void cancelJob(job)}
                            tone="danger"
                          >
                            Cancelar
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  </details>
                );
              })}
            </div>
          ) : (
            <EmptyState
              description="Todavía no se han solicitado rastreos desde la API."
              title="La cola está vacía"
            />
          )}
        </article>
      </section>

      <Modal
        description="Esta revisión no consulta tiendas todavía. El trabajo solo se crea cuando confirmas el siguiente paso."
        onClose={() => {
          if (!submitting) {
            setReviewOpen(false);
          }
        }}
        open={reviewOpen}
        title="Confirma el trabajo de rastreo"
      >
        <div className="crawl-confirmation">
          <div className="crawl-confirmation__summary">
            <span>Productos seleccionados</span>
            <strong>{selectedProducts.length}</strong>
          </div>
          <ul>
            {selectedProducts.map((product) => (
              <li key={product.id}>
                <span>
                  <strong>{product.label}</strong>
                  <small>{titleCase(product.store_slug)}</small>
                </span>
                <StatusPill
                  tone={
                    productIsDue(
                      product,
                      data?.stores ?? [],
                      data?.loadedAt ?? 0,
                    )
                      ? "success"
                      : "warning"
                  }
                >
                  {productIsDue(
                    product,
                    data?.stores ?? [],
                    data?.loadedAt ?? 0,
                  )
                    ? "Elegible"
                    : "Sujeto a intervalo"}
                </StatusPill>
              </li>
            ))}
          </ul>
          {workerUnavailable ? (
            <div className="job-warning">
              El trabajador no está activo. Si confirmas, el trabajo quedará
              guardado en la cola hasta que vuelva a funcionar.
            </div>
          ) : null}
          <p>
            Al confirmar, el servidor revalidará límites y pausas. Un producto
            que todavía no corresponda será omitido responsablemente.
          </p>
          <div className="crawl-confirmation__actions">
            <Button
              disabled={submitting}
              onClick={() => setReviewOpen(false)}
              tone="secondary"
              type="button"
            >
              Volver
            </Button>
            <Button
              disabled={submitting || !selectedProducts.length}
              onClick={() => void createJob()}
              type="button"
            >
              <RadarIcon />
              {submitting ? "Enviando…" : "Confirmar y enviar a la cola"}
            </Button>
          </div>
        </div>
      </Modal>

      <section className="surface">
        <header className="surface__header">
          <div>
            <p className="section-kicker">Scrapy</p>
            <h2>Últimas ejecuciones</h2>
          </div>
        </header>
        {runs.length ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Tienda</th>
                  <th>Inicio</th>
                  <th>Solicitudes</th>
                  <th>Observaciones</th>
                  <th>Errores</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>{titleCase(run.store_slug)}</td>
                    <td>{formatDateTime(run.started_at)}</td>
                    <td>{run.requested_url_count}</td>
                    <td>{run.observation_count}</td>
                    <td>{run.error_count}</td>
                    <td>
                      <StatusPill tone={jobTone(run.status)}>
                        {runStatusLabels[run.status]}
                      </StatusPill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            description="Scrapy todavía no ha registrado una ejecución."
            title="Sin corridas"
          />
        )}
      </section>
    </div>
  );
}
