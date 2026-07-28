"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiClient } from "@/lib/api";
import { formatCurrency, formatPercent, formatRelativeTime } from "@/lib/format";
import {
  classificationLabels,
  classificationTones,
  operationalTone,
} from "@/lib/presentation";
import type {
  ConfirmationRead,
  CrawlJobRead,
  OfferRead,
  StoreRead,
} from "@/lib/types";

import type { AdminView } from "../components/admin-shell";
import { ExternalLinkIcon, RadarIcon } from "../components/icons";
import {
  Button,
  EmptyState,
  LoadingBlock,
  StatusPill,
} from "../components/ui";

interface SummaryData {
  confirmations: ConfirmationRead[];
  confirmationsHasMore: boolean;
  jobs: CrawlJobRead[];
  offers: OfferRead[];
  offersHasMore: boolean;
  stores: StoreRead[];
}

export function SummaryView({
  client,
  onNavigate,
  refreshNonce,
}: {
  client: ApiClient;
  onNavigate: (view: AdminView) => void;
  refreshNonce: number;
}) {
  const [data, setData] = useState<SummaryData | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [stores, offers, confirmations, jobs] = await Promise.all([
        client.listStores(),
        client.listOffers({ state: "active", limit: 100 }),
        client.listConfirmations({ active_only: true, limit: 100 }),
        client.listCrawlJobs({ limit: 8 }),
      ]);
      setData({
        stores: stores.data,
        offers: offers.data.items,
        offersHasMore: offers.data.has_more,
        confirmations: confirmations.data.items,
        confirmationsHasMore: confirmations.data.has_more,
        jobs: jobs.data.items,
      });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "No se pudo cargar el resumen.");
    }
  }, [client]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load, refreshNonce]);

  if (!data && !error) {
    return <LoadingBlock label="Preparando el panorama de oportunidades" />;
  }

  if (error && !data) {
    return (
      <EmptyState
        action={<Button onClick={() => void load()}>Reintentar</Button>}
        description={error}
        title="No pudimos preparar el resumen"
      />
    );
  }

  const stores = data?.stores ?? [];
  const offers = data?.offers ?? [];
  const confirmations = data?.confirmations ?? [];
  const openJobs =
    data?.jobs.filter((job) =>
      ["queued", "running", "retrying"].includes(job.status),
    ) ?? [];
  const trackedProducts = stores.reduce(
    (total, store) => total + store.tracked_products,
    0,
  );
  const healthyStores = stores.filter(
    (store) => store.enabled && store.health.toLowerCase() === "healthy",
  ).length;

  return (
    <div className="view-stack">
      {error ? <div className="inline-error">{error}</div> : null}

      <section className="summary-hero">
        <div className="summary-hero__story">
          <p className="hero-kicker">Panorama actual</p>
          <h2>
            El mercado se mueve.
            <br />
            Tu radar encontró {offers.length}
            {data?.offersHasMore ? "+" : ""} oportunidades.
          </h2>
          <p>
            Precios públicos de tiendas peruanas, revisados y organizados para
            decidir con contexto.
          </p>
        </div>
        <div className="summary-hero__action">
          <span>Próxima acción</span>
          <strong>
            Actualiza el catálogo y comprueba los precios que ya estén pendientes.
          </strong>
          <Button onClick={() => onNavigate("crawls")}>
            <RadarIcon />
            Rastrear productos
          </Button>
        </div>
      </section>

      <section className="kpi-grid" aria-label="Indicadores principales">
        <article className="kpi-card kpi-card--accent">
          <span>Ofertas activas</span>
          <strong>
            {offers.length}
            {data?.offersHasMore ? "+" : ""}
          </strong>
          <small>confirmadas y vigentes</small>
        </article>
        <article className="kpi-card">
          <span>Productos monitoreados</span>
          <strong>{trackedProducts}</strong>
          <small>en el catálogo</small>
        </article>
        <article className="kpi-card">
          <span>Por confirmar</span>
          <strong>
            {confirmations.length}
            {data?.confirmationsHasMore ? "+" : ""}
          </strong>
          <small>segunda observación</small>
        </article>
        <article className="kpi-card">
          <span>Tiendas saludables</span>
          <strong>
            {healthyStores}/{stores.length}
          </strong>
          <small>adaptadores disponibles</small>
        </article>
      </section>

      <section className="summary-grid">
        <article className="surface">
          <header className="surface__header">
            <div>
              <p className="section-kicker">Detección reciente</p>
              <h2>Ofertas destacadas</h2>
            </div>
            <button className="text-link" onClick={() => onNavigate("offers")} type="button">
              Ver todas <span aria-hidden="true">→</span>
            </button>
          </header>
          {offers.length ? (
            <div className="offer-list">
              {offers.slice(0, 5).map((offer, index) => (
                <article className="offer-list__row" key={offer.id}>
                  <span className="offer-index">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div className="offer-list__product">
                    <strong>{offer.product_label || offer.title}</strong>
                    <span>{offer.store_slug}</span>
                  </div>
                  <StatusPill tone={classificationTones[offer.classification]}>
                    {classificationLabels[offer.classification]}
                  </StatusPill>
                  <strong className="offer-price">
                    {formatCurrency(offer.current_price, offer.currency)}
                  </strong>
                  <span className="discount-badge">
                    −{formatPercent(offer.discount_percent)}
                  </span>
                  <a
                    aria-label={`Abrir ${offer.product_label}`}
                    className="icon-link"
                    href={offer.source_url}
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    <ExternalLinkIcon />
                  </a>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState
              description="Todavía no hay detecciones activas. Ejecuta un rastreo cuando algún producto esté pendiente."
              title="Sin ofertas activas"
            />
          )}
        </article>

        <aside className="surface health-card">
          <header className="surface__header">
            <div>
              <p className="section-kicker">Estado operativo</p>
              <h2>Salud de tiendas</h2>
            </div>
          </header>
          <div className="health-card__summary">
            <span>{healthyStores}/{stores.length}</span>
            <div>
              <strong>
                {healthyStores === stores.length
                  ? "Adaptadores disponibles"
                  : "Revisa los estados"}
              </strong>
              <small>La API reporta el estado actual</small>
            </div>
          </div>
          <div className="health-card__stores">
            {stores.map((store) => (
              <div key={store.slug}>
                <span>
                  <i className={`health-dot health-dot--${operationalTone(store.health)}`} />
                  {store.display_name}
                </span>
                <StatusPill tone={operationalTone(store.health)}>
                  {store.health}
                </StatusPill>
              </div>
            ))}
          </div>
          <div className="health-card__jobs">
            <span>Trabajos abiertos</span>
            <strong>{openJobs.length}</strong>
            <small>
              {openJobs[0]
                ? `Último cambio ${formatRelativeTime(openJobs[0].updated_at)}`
                : "La cola está libre"}
            </small>
          </div>
        </aside>
      </section>
    </div>
  );
}
