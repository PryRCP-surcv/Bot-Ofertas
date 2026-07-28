"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiClient } from "@/lib/api";
import {
  formatCurrency,
  formatDateTime,
  formatPercent,
  titleCase,
} from "@/lib/format";
import {
  classificationLabels,
  classificationTones,
  notificationLabels,
} from "@/lib/presentation";
import type {
  DealClassification,
  OfferRead,
  OfferState,
  StoreRead,
} from "@/lib/types";

import { ExternalLinkIcon } from "../components/icons";
import { Button, EmptyState, LoadingBlock, StatusPill } from "../components/ui";

const offerTabs: Array<{ id: OfferState; label: string; description: string }> = [
  {
    id: "active",
    label: "Activas",
    description: "Confirmadas, vigentes y disponibles durante las últimas 24 horas.",
  },
  {
    id: "awaiting",
    label: "Por confirmar",
    description: "Candidatas que necesitan una segunda observación compatible.",
  },
  {
    id: "history",
    label: "Historial",
    description: "Decisiones anteriores conservadas para auditoría.",
  },
];

export function OffersView({
  client,
  refreshNonce,
}: {
  client: ApiClient;
  refreshNonce: number;
}) {
  const [state, setState] = useState<OfferState>("active");
  const [classification, setClassification] = useState<
    DealClassification | ""
  >("");
  const [storeSlug, setStoreSlug] = useState("");
  const [includeRejected, setIncludeRejected] = useState(false);
  const [stores, setStores] = useState<StoreRead[]>([]);
  const [offers, setOffers] = useState<OfferRead[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  const loadOffers = useCallback(
    async (cursor?: string) => {
      const append = Boolean(cursor);
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      setError("");
      try {
        const response = await client.listOffers({
          state,
          classification: classification || undefined,
          store_slug: storeSlug || undefined,
          include_rejected: includeRejected,
          cursor,
          limit: 30,
        });
        setOffers((current) =>
          append ? [...current, ...response.data.items] : response.data.items,
        );
        setNextCursor(response.data.next_cursor);
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "No se pudieron consultar las ofertas.",
        );
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [classification, client, includeRejected, state, storeSlug],
  );

  useEffect(() => {
    void client
      .listStores()
      .then((response) => setStores(response.data))
      .catch(() => setStores([]));
  }, [client]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadOffers();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadOffers, refreshNonce]);

  const currentTab = offerTabs.find((tab) => tab.id === state) ?? offerTabs[0];

  return (
    <div className="view-stack">
      <section className="view-heading">
        <div>
          <p className="section-kicker">Clasificación del detector</p>
          <h2>Oportunidades con evidencia</h2>
          <p>
            Consulta la clasificación, confianza y razones que justifican cada
            detección. El panel no compra ni modifica ofertas.
          </p>
        </div>
      </section>

      <section className="surface">
        <div className="tabs" role="tablist" aria-label="Estado de las ofertas">
          {offerTabs.map((tab) => (
            <button
              aria-selected={state === tab.id}
              className={state === tab.id ? "active" : ""}
              key={tab.id}
              onClick={() => setState(tab.id)}
              role="tab"
              type="button"
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="filter-bar">
          <p>{currentTab.description}</p>
          <div className="filter-controls">
            <label>
              <span className="sr-only">Clasificación</span>
              <select
                onChange={(event) =>
                  setClassification(
                    event.target.value as DealClassification | "",
                  )
                }
                value={classification}
              >
                <option value="">Toda clasificación</option>
                <option value="good_deal">Buena oferta</option>
                <option value="exceptional_deal">Oferta excepcional</option>
                <option value="possible_price_error">Posible error</option>
                {state === "history" ? <option value="none">Sin oferta</option> : null}
              </select>
            </label>
            <label>
              <span className="sr-only">Tienda</span>
              <select
                onChange={(event) => setStoreSlug(event.target.value)}
                value={storeSlug}
              >
                <option value="">Todas las tiendas</option>
                {stores.map((store) => (
                  <option key={store.slug} value={store.slug}>
                    {store.display_name}
                  </option>
                ))}
              </select>
            </label>
            {state === "history" ? (
              <label className="checkbox-field">
                <input
                  checked={includeRejected}
                  onChange={(event) => setIncludeRejected(event.target.checked)}
                  type="checkbox"
                />
                Incluir rechazadas
              </label>
            ) : null}
          </div>
        </div>

        {loading ? (
          <LoadingBlock label="Consultando detecciones" />
        ) : error && offers.length === 0 ? (
          <EmptyState
            action={<Button onClick={() => void loadOffers()}>Reintentar</Button>}
            description={error}
            title="No se pudieron cargar las ofertas"
          />
        ) : offers.length === 0 ? (
          <EmptyState
            description="No hay resultados para esta pestaña y los filtros seleccionados."
            title={`Sin ofertas ${currentTab.label.toLowerCase()}`}
          />
        ) : (
          <>
            {error ? <div className="inline-error">{error}</div> : null}
            <div className="offer-cards">
              {offers.map((offer) => (
                <article className="offer-card" key={offer.id}>
                  <div className="offer-card__top">
                    <div>
                      <StatusPill tone={classificationTones[offer.classification]}>
                        {classificationLabels[offer.classification]}
                      </StatusPill>
                      <span className="offer-card__store">
                        {titleCase(offer.store_slug)}
                      </span>
                    </div>
                    <a
                      className="icon-link"
                      href={offer.source_url}
                      rel="noopener noreferrer"
                      target="_blank"
                      title="Abrir producto en la tienda"
                    >
                      <ExternalLinkIcon />
                    </a>
                  </div>
                  <h3>{offer.product_label || offer.title}</h3>
                  {offer.title !== offer.product_label ? <p>{offer.title}</p> : null}
                  <div className="offer-card__price">
                    <strong>
                      {formatCurrency(offer.current_price, offer.currency)}
                    </strong>
                    <span>
                      Referencia{" "}
                      {formatCurrency(offer.reference_price, offer.currency)}
                    </span>
                    <b>−{formatPercent(offer.discount_percent)}</b>
                  </div>
                  <div className="confidence-meter">
                    <div>
                      <span>Confianza</span>
                      <strong>{offer.confidence_score}/100</strong>
                    </div>
                    <span>
                      <i style={{ width: `${offer.confidence_score}%` }} />
                    </span>
                  </div>
                  <div className="offer-card__meta">
                    <span>
                      <small>Notificación</small>
                      {notificationLabels[offer.notification_status]}
                    </span>
                    <span>
                      <small>Confirmación</small>
                      {titleCase(offer.confirmation_status)}
                    </span>
                    <span>
                      <small>Detectada</small>
                      {formatDateTime(offer.detected_at)}
                    </span>
                  </div>
                  <div className="offer-card__reason">
                    <strong>Por qué se detectó</strong>
                    <p>
                      {offer.reasons[0] ??
                        offer.rejection_reasons[0] ??
                        "El detector no registró una razón legible."}
                    </p>
                    {offer.quality_flags.length ? (
                      <small>
                        Señales de calidad: {offer.quality_flags.join(", ")}
                      </small>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
            {nextCursor ? (
              <div className="load-more">
                <Button
                  disabled={loadingMore}
                  onClick={() => void loadOffers(nextCursor)}
                  tone="secondary"
                >
                  {loadingMore ? "Cargando…" : "Cargar más"}
                </Button>
              </div>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
