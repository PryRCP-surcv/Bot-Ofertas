"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiClient } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type {
  TelegramDestinationStatusRead,
  TelegramDistributionStatusRead,
} from "@/lib/types";

import { PaperPlaneIcon, RefreshIcon } from "../components/icons";
import { Button, EmptyState, LoadingBlock, StatusPill } from "../components/ui";

export function DistributionView({
  client,
  onNotify,
  refreshNonce,
}: {
  client: ApiClient;
  onNotify: (message: string, tone: "success" | "error") => void;
  refreshNonce: number;
}) {
  const [status, setStatus] =
    useState<TelegramDistributionStatusRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [testingDestination, setTestingDestination] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await client.getTelegramDistribution();
      setStatus(response.data);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "No se pudo consultar la distribución por Telegram.",
      );
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load, refreshNonce]);

  async function sendTest(destination: TelegramDestinationStatusRead) {
    if (
      !window.confirm(
        `Se enviará un mensaje fijo al destino ${destination.audience.toUpperCase()}. ¿Continuar?`,
      )
    ) {
      return;
    }
    setTestingDestination(destination.channel);
    try {
      const response = await client.testTelegramDistribution(
        destination.channel as "telegram_free" | "telegram_vip",
      );
      if (response.data.sent) {
        onNotify(
          `Telegram ${destination.audience.toUpperCase()} recibió el mensaje de prueba.`,
          "success",
        );
      } else {
        onNotify(
          response.data.detail ??
            "Telegram no aceptó el mensaje. Revisa la configuración.",
          "error",
        );
      }
      await load();
    } catch (testError) {
      onNotify(
        testError instanceof Error
          ? testError.message
          : "No se pudo enviar el mensaje de prueba.",
        "error",
      );
    } finally {
      setTestingDestination("");
    }
  }

  if (loading && !status) {
    return <LoadingBlock label="Consultando distribución y cobertura" />;
  }

  if (error && !status) {
    return (
      <EmptyState
        action={<Button onClick={() => void load()}>Reintentar</Button>}
        description={error}
        title="No se pudo consultar Telegram"
      />
    );
  }

  if (!status) {
    return null;
  }

  const waiting =
    status.queue_counts.pending + status.queue_counts.retrying;
  const failed = status.queue_counts.failed;
  const free = status.destinations.find(
    (destination) => destination.audience === "free",
  );

  return (
    <div className="view-stack">
      {error ? <div className="inline-error">{error}</div> : null}
      <section className="distribution-hero">
        <div className="distribution-hero__copy">
          <p className="section-kicker">Fase 6.7A · distribución auditable</p>
          <h2>Un emisor, varios destinos independientes</h2>
          <p>
            Cada oferta conserva su destino, regla, horario y resultado. El
            canal gratuito continúa siendo el destino principal; el espejo VIP
            se activa únicamente cuando configures su identificador.
          </p>
          <div className="distribution-hero__status">
            <StatusPill tone={status.ready ? "success" : "warning"}>
              {status.ready ? "Free operativo" : "Free incompleto"}
            </StatusPill>
            <span>
              {status.destinations.length} destino
              {status.destinations.length === 1 ? "" : "s"} · sin exponer
              credenciales
            </span>
          </div>
        </div>
        <div className="distribution-hero__action">
          <PaperPlaneIcon />
          <strong>Estado del canal principal</strong>
          <p>
            {free?.last_sent_at
              ? `Último envío: ${formatDateTime(free.last_sent_at)}`
              : "Todavía no hay una entrega registrada."}
          </p>
          <Button onClick={() => void load()} type="button">
            <RefreshIcon className={loading ? "spin" : ""} />
            Actualizar estado
          </Button>
        </div>
      </section>

      <section className="distribution-metrics" aria-label="Estado de distribución">
        <DistributionMetric
          detail={`${status.coverage.successful_products_24h} de ${status.coverage.active_products} productos`}
          label="Cobertura 24 h"
          value={`${status.coverage.coverage_percent}%`}
          warning={!status.coverage.meets_target}
        />
        <DistributionMetric
          detail={
            status.analysis_backlog.pending_observations
              ? `${status.analysis_backlog.oldest_age_hours} h de antigüedad · ~${status.analysis_backlog.estimated_cycles} ciclo(s)`
              : "sin observaciones atrasadas"
          }
          label="Pendientes de analizar"
          value={status.analysis_backlog.pending_observations}
          warning={status.analysis_backlog.warning}
        />
        <DistributionMetric
          detail="ofertas únicas publicadas"
          label="Alertas 24 h"
          value={status.concentration.unique_alerts}
        />
        <DistributionMetric
          detail="pendientes o en reintento"
          label="Esperando envío"
          value={waiting}
        />
        <DistributionMetric
          detail="agotaron sus intentos"
          label="Fallidas"
          value={failed}
          warning={failed > 0}
        />
      </section>

      <section className="distribution-destinations">
        {status.destinations.map((destination) => (
          <article className="panel-card destination-card" key={destination.channel}>
            <div className="panel-card__header">
              <div>
                <p className="section-kicker">
                  Audiencia {destination.audience.toUpperCase()}
                </p>
                <h2>{destination.channel}</h2>
              </div>
              <StatusPill tone={destination.ready ? "success" : "warning"}>
                {destination.ready ? "Listo" : "Sin configurar"}
              </StatusPill>
            </div>
            <dl>
              <div>
                <dt>Modo</dt>
                <dd>{dispatchModeLabel(destination.dispatch_mode)}</dd>
              </div>
              <div>
                <dt>Enviadas 24 h</dt>
                <dd>{destination.sent_24h}</dd>
              </div>
              <div>
                <dt>Enviadas 7 días</dt>
                <dd>{destination.sent_7d}</dd>
              </div>
              <div>
                <dt>En cola</dt>
                <dd>
                  {destination.queue_counts.pending +
                    destination.queue_counts.retrying}
                </dd>
              </div>
            </dl>
            <Button
              disabled={
                !destination.ready ||
                testingDestination === destination.channel
              }
              onClick={() => void sendTest(destination)}
              type="button"
            >
              <RefreshIcon
                className={
                  testingDestination === destination.channel ? "spin" : ""
                }
              />
              {testingDestination === destination.channel
                ? "Enviando"
                : "Enviar prueba"}
            </Button>
          </article>
        ))}
      </section>

      <section className="distribution-layout">
        <article className="panel-card distribution-breakdown">
          <div className="panel-card__header">
            <div>
              <p className="section-kicker">Últimas 24 horas</p>
              <h2>Distribución por categoría</h2>
            </div>
            <StatusPill
              tone={status.concentration.warning ? "warning" : "success"}
            >
              {status.concentration.warning
                ? "Concentración alta"
                : "Sin concentración crítica"}
            </StatusPill>
          </div>
          {status.concentration.categories.length ? (
            <div className="distribution-bars">
              {status.concentration.categories.map((category) => (
                <div className="distribution-bar" key={category.key}>
                  <div>
                    <strong>{category.label}</strong>
                    <span>
                      {category.count} · {category.percentage}%
                    </span>
                  </div>
                  <progress
                    max="100"
                    value={Number(category.percentage)}
                  />
                </div>
              ))}
            </div>
          ) : (
            <p className="muted-copy">
              Todavía no hay alertas enviadas durante esta ventana.
            </p>
          )}
        </article>

        <aside className="panel-card distribution-health">
          <div className="panel-card__header">
            <div>
              <p className="section-kicker">Objetivo operativo</p>
              <h2>Cobertura por tienda</h2>
            </div>
          </div>
          <div className="coverage-list">
            {status.coverage.stores.map((store) => (
              <div className="coverage-row" key={store.store_slug}>
                <div>
                  <strong>{store.store_slug}</strong>
                  <span>
                    {store.successful_products_24h}/{store.active_products}
                  </span>
                </div>
                <StatusPill tone={store.meets_target ? "success" : "warning"}>
                  {store.coverage_percent}%
                </StatusPill>
              </div>
            ))}
          </div>
          <p className="distribution-note">
            Objetivo: {status.coverage.target_percent}% diario. Productos aún
            clasificados como “Otros”:{" "}
            {status.concentration.uncategorized_catalog_products}.
          </p>
        </aside>
      </section>
    </div>
  );
}

function dispatchModeLabel(
  mode: TelegramDestinationStatusRead["dispatch_mode"],
) {
  if (mode === "mirrored") return "Espejo de validación";
  if (mode === "delayed") return "Entrega retrasada";
  return "Inmediato";
}

function DistributionMetric({
  detail,
  label,
  value,
  warning = false,
}: {
  detail: string;
  label: string;
  value: number | string;
  warning?: boolean;
}) {
  return (
    <article
      className={warning ? "distribution-metric warning" : "distribution-metric"}
    >
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}
