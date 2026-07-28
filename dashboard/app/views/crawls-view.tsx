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
} from "@/lib/presentation";
import type {
  CrawlJobRead,
  CrawlRunRead,
  ProductRead,
  StoreRead,
} from "@/lib/types";

import { RadarIcon, SearchIcon } from "../components/icons";
import { Button, EmptyState, LoadingBlock, StatusPill } from "../components/ui";

interface CrawlData {
  jobs: CrawlJobRead[];
  loadedAt: number;
  products: ProductRead[];
  productsHasMore: boolean;
  runs: CrawlRunRead[];
  stores: StoreRead[];
}

export function CrawlsView({
  client,
  onNotify,
  refreshNonce,
}: {
  client: ApiClient;
  onNotify: (message: string, tone: "success" | "error") => void;
  refreshNonce: number;
}) {
  const [data, setData] = useState<CrawlData | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
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

  return (
    <div className="view-stack">
      {error ? <div className="inline-error">{error}</div> : null}
      <section className="view-heading">
        <div>
          <p className="section-kicker">Cola responsable</p>
          <h2>Solicita una revisión sin saltar límites</h2>
          <p>
            “Rastrear ahora” coloca un trabajo en la cola. El monitor solo
            consultará productos pendientes y respetará intervalos, cuotas,
            pausas, robots.txt y CAPTCHA.
          </p>
        </div>
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
              onClick={() => void createJob()}
            >
              <RadarIcon />
              {submitting ? "Enviando…" : "Enviar a la cola"}
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
