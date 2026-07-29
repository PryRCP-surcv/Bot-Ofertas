"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiClient } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { TelegramDistributionStatusRead } from "@/lib/types";

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
  const [testing, setTesting] = useState(false);
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

  async function sendTest() {
    if (
      !window.confirm(
        "Se enviará un mensaje de prueba al grupo o canal configurado. ¿Continuar?",
      )
    ) {
      return;
    }
    setTesting(true);
    try {
      const response = await client.testTelegramDistribution();
      if (response.data.sent) {
        onNotify("Telegram recibió correctamente el mensaje de prueba.", "success");
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
      setTesting(false);
    }
  }

  if (loading && !status) {
    return <LoadingBlock label="Consultando el canal beta" />;
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

  return (
    <div className="view-stack">
      {error ? <div className="inline-error">{error}</div> : null}
      <section className="distribution-hero">
        <div className="distribution-hero__copy">
          <p className="section-kicker">Primera audiencia de pago</p>
          <h2>Un solo grupo, alertas automáticas</h2>
          <p>
            El monitor publica las ofertas confirmadas en el chat de Telegram
            configurado. Tú controlas manualmente quién entra o sale del grupo
            durante esta beta económica.
          </p>
          <div className="distribution-hero__status">
            <StatusPill tone={status.ready ? "success" : "warning"}>
              {status.ready ? "Canal listo" : "Configuración incompleta"}
            </StatusPill>
            <span>
              Membresías manuales · cobros externos · sin exponer credenciales
            </span>
          </div>
        </div>
        <div className="distribution-hero__action">
          <PaperPlaneIcon />
          <strong>Prueba el destino antes de invitar personas</strong>
          <p>
            El mensaje es fijo y no permite enviar contenido arbitrario desde el
            panel.
          </p>
          <Button
            disabled={testing || !status.ready}
            onClick={() => void sendTest()}
            type="button"
          >
            <RefreshIcon className={testing ? "spin" : ""} />
            {testing ? "Enviando" : "Enviar prueba"}
          </Button>
        </div>
      </section>

      <section className="distribution-metrics" aria-label="Estado de entregas">
        <DistributionMetric
          detail="enviadas al destino beta"
          label="Entregas correctas"
          value={status.queue_counts.sent}
        />
        <DistributionMetric
          detail="pendientes o en reintento"
          label="Esperando envío"
          value={waiting}
        />
        <DistributionMetric
          detail="agotaron sus intentos"
          label="Fallidas"
          value={status.queue_counts.failed}
          warning={status.queue_counts.failed > 0}
        />
      </section>

      <section className="distribution-layout">
        <article className="panel-card distribution-flow">
          <div className="panel-card__header">
            <div>
              <p className="section-kicker">Flujo comercial beta</p>
              <h2>Cómo administrar suscriptores ahora</h2>
            </div>
          </div>
          <ol>
            <li>
              <span>1</span>
              <div>
                <strong>Confirmas el pago por tu medio elegido</strong>
                <p>El bot no almacena tarjetas ni procesa cobros en esta etapa.</p>
              </div>
            </li>
            <li>
              <span>2</span>
              <div>
                <strong>Agregas o invitas a la persona en Telegram</strong>
                <p>
                  Mantén el grupo privado y elimina manualmente accesos vencidos.
                </p>
              </div>
            </li>
            <li>
              <span>3</span>
              <div>
                <strong>El trabajador publica cada oferta confirmada</strong>
                <p>
                  La cola durable evita perder alertas ante fallos temporales.
                </p>
              </div>
            </li>
          </ol>
        </article>

        <aside className="panel-card distribution-health">
          <div className="panel-card__header">
            <div>
              <p className="section-kicker">Última actividad</p>
              <h2>Salud del canal</h2>
            </div>
          </div>
          <dl>
            <div>
              <dt>Último envío</dt>
              <dd>
                {status.last_sent_at
                  ? formatDateTime(status.last_sent_at)
                  : "Todavía no hay entregas"}
              </dd>
            </div>
            <div>
              <dt>Último error</dt>
              <dd>
                {status.last_error_at
                  ? formatDateTime(status.last_error_at)
                  : "Sin errores registrados"}
              </dd>
            </div>
            <div>
              <dt>Detalle seguro</dt>
              <dd>{status.last_error ?? "El canal opera sin incidencias."}</dd>
            </div>
          </dl>
        </aside>
      </section>
    </div>
  );
}

function DistributionMetric({
  detail,
  label,
  value,
  warning = false,
}: {
  detail: string;
  label: string;
  value: number;
  warning?: boolean;
}) {
  return (
    <article className={warning ? "distribution-metric warning" : "distribution-metric"}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}
