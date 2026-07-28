"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiClient } from "@/lib/api";
import { formatDateTime, formatRelativeTime, titleCase } from "@/lib/format";
import { operationalTone } from "@/lib/presentation";
import type { StoreRead } from "@/lib/types";

import { Button, EmptyState, LoadingBlock, StatusPill } from "../components/ui";

export function StoresView({
  client,
  refreshNonce,
}: {
  client: ApiClient;
  refreshNonce: number;
}) {
  const [stores, setStores] = useState<StoreRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await client.listStores();
      setStores(response.data);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "No se pudo consultar el estado de las tiendas.",
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

  return (
    <div className="view-stack">
      <section className="view-heading">
        <div>
          <p className="section-kicker">Cobertura controlada</p>
          <h2>Adapters de tiendas peruanas</h2>
          <p>
            Esta pantalla es informativa. Añadir una tienda nueva requiere un
            adapter con dominio, selectores, límites y pruebas propias.
          </p>
        </div>
      </section>

      {loading ? (
        <LoadingBlock label="Comprobando adapters" />
      ) : error && stores.length === 0 ? (
        <EmptyState
          action={<Button onClick={() => void load()}>Reintentar</Button>}
          description={error}
          title="No se pudo consultar las tiendas"
        />
      ) : stores.length === 0 ? (
        <EmptyState
          description="La API no reportó adapters habilitados."
          title="Sin tiendas configuradas"
        />
      ) : (
        <>
          {error ? <div className="inline-error">{error}</div> : null}
          <section className="store-grid">
            {stores.map((store) => {
              const paused =
                store.paused_until && new Date(store.paused_until) > new Date();
              const stateLabel = !store.enabled
                ? "Deshabilitada"
                : paused
                  ? "Pausada"
                  : titleCase(store.health);
              const stateTone = !store.enabled
                ? "danger"
                : paused
                  ? "warning"
                  : operationalTone(store.health);

              return (
                <article className="store-card" key={store.slug}>
                  <header>
                    <span className="store-monogram">
                      {store.display_name.slice(0, 2).toUpperCase()}
                    </span>
                    <div>
                      <h3>{store.display_name}</h3>
                      <p>{store.hosts.join(", ")}</p>
                    </div>
                    <StatusPill tone={stateTone}>{stateLabel}</StatusPill>
                  </header>

                  {paused ? (
                    <div className="store-alert">
                      <strong>Pausa automática vigente</strong>
                      <span>
                        Hasta {formatDateTime(store.paused_until)}
                        {store.pause_reason ? ` · ${store.pause_reason}` : ""}
                      </span>
                    </div>
                  ) : null}

                  <div className="store-metrics">
                    <div>
                      <span>Productos activos</span>
                      <strong>{store.active_products}</strong>
                    </div>
                    <div>
                      <span>Máximo por vuelta</span>
                      <strong>{store.max_targets_per_run}</strong>
                    </div>
                    <div>
                      <span>Intervalo mínimo</span>
                      <strong>{store.minimum_interval_minutes} min</strong>
                    </div>
                    <div>
                      <span>Bloqueos seguidos</span>
                      <strong>{store.consecutive_blocks}</strong>
                    </div>
                  </div>

                  <div className="store-card__note">
                    <strong>Regla operativa</strong>
                    <p>{store.notes || "Sin notas adicionales."}</p>
                    <span>
                      {store.requires_explicit_product_url
                        ? "Requiere URL explícita por producto."
                        : "Admite descubrimiento configurado."}
                    </span>
                  </div>

                  <footer>
                    <div>
                      <span>Última ejecución</span>
                      <strong title={formatDateTime(store.last_run_finished_at)}>
                        {formatRelativeTime(
                          store.last_run_finished_at ??
                            store.last_run_started_at,
                        )}
                      </strong>
                    </div>
                    {store.last_run_status ? (
                      <StatusPill tone={operationalTone(store.last_run_status)}>
                        {titleCase(store.last_run_status)}
                      </StatusPill>
                    ) : (
                      <span className="muted-text">Aún sin ejecuciones</span>
                    )}
                  </footer>
                </article>
              );
            })}
          </section>
        </>
      )}

      <section className="info-banner">
        <div>
          <span aria-hidden="true">i</span>
          <div>
            <strong>¿Por qué no hay un botón “Agregar tienda”?</strong>
            <p>
              Cada comercio publica datos con una estructura distinta. Para
              mantener el bot robusto y responsable, una tienda se incorpora
              mediante código revisado y pruebas, no mediante una URL genérica.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
