"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiClient } from "@/lib/api";
import { formatDateTime, formatRelativeTime, titleCase } from "@/lib/format";
import type {
  DiscoveryCandidateRead,
  DiscoveryCandidateStatus,
  DiscoveryRunRead,
  DiscoverySourceRead,
  UUID,
} from "@/lib/types";

import {
  CheckIcon,
  ExternalLinkIcon,
  RadarIcon,
  SearchIcon,
} from "../components/icons";
import { Button, EmptyState, LoadingBlock, StatusPill } from "../components/ui";

const candidateStatuses: Array<{
  value: DiscoveryCandidateStatus;
  label: string;
}> = [
  { value: "pending", label: "Pendientes" },
  { value: "approved", label: "Aprobados" },
  { value: "rejected", label: "Rechazados" },
  { value: "duplicate", label: "Duplicados" },
  { value: "policy_blocked", label: "Bloqueados por política" },
  { value: "unavailable", label: "No disponibles" },
];

function statusTone(
  status: string,
): "success" | "warning" | "danger" | "info" | "neutral" {
  if (["succeeded", "approved"].includes(status)) return "success";
  if (["running", "partial", "pending", "never"].includes(status)) return "warning";
  if (["failed", "blocked", "policy_blocked"].includes(status)) return "danger";
  if (status === "duplicate") return "info";
  return "neutral";
}

export function DiscoveryView({
  client,
  onNotify,
  refreshNonce,
}: {
  client: ApiClient;
  onNotify: (message: string, tone: "success" | "error") => void;
  refreshNonce: number;
}) {
  const [sources, setSources] = useState<DiscoverySourceRead[]>([]);
  const [candidates, setCandidates] = useState<DiscoveryCandidateRead[]>([]);
  const [runs, setRuns] = useState<DiscoveryRunRead[]>([]);
  const [candidateStatus, setCandidateStatus] =
    useState<DiscoveryCandidateStatus>("pending");
  const [store, setStore] = useState("");
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [selected, setSelected] = useState<UUID[]>([]);
  const [rejectReason, setRejectReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [sourceResponse, candidateResponse, runResponse] =
        await Promise.all([
          client.listDiscoverySources(),
          client.listDiscoveryCandidates({
            limit: 100,
            status: candidateStatus,
            store_slug: store || undefined,
            search: appliedSearch || undefined,
          }),
          client.listDiscoveryRuns({ limit: 12, store_slug: store || undefined }),
        ]);
      setSources(sourceResponse.data);
      setCandidates(candidateResponse.data.items);
      setRuns(runResponse.data);
      setSelected([]);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "No se pudo consultar el descubrimiento.",
      );
    } finally {
      setLoading(false);
    }
  }, [appliedSearch, candidateStatus, client, store]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load, refreshNonce]);

  const pendingIds = useMemo(
    () =>
      candidates
        .filter((candidate) => candidate.status === "pending")
        .map((candidate) => candidate.id),
    [candidates],
  );

  async function scheduleSource(source: DiscoverySourceRead) {
    setSubmitting(true);
    try {
      await client.scheduleDiscoverySource(source.id);
      onNotify(
        `${titleCase(source.store_slug)} quedó programada para el próximo ciclo del worker.`,
        "success",
      );
      await load();
    } catch (scheduleError) {
      onNotify(
        scheduleError instanceof Error
          ? scheduleError.message
          : "No se pudo programar la fuente.",
        "error",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function reviewOne(
    candidate: DiscoveryCandidateRead,
    action: "approve" | "reject",
  ) {
    if (action === "reject" && !rejectReason.trim()) {
      onNotify("Escribe un motivo antes de rechazar.", "error");
      return;
    }
    setSubmitting(true);
    try {
      await client.reviewDiscoveryCandidate(candidate.id, {
        action,
        label: action === "approve" ? candidate.label : undefined,
        reason: action === "reject" ? rejectReason.trim() : undefined,
      });
      onNotify(
        action === "approve"
          ? "Producto aprobado y agregado al monitoreo."
          : "Candidato rechazado con motivo auditado.",
        "success",
      );
      await load();
    } catch (reviewError) {
      onNotify(
        reviewError instanceof Error
          ? reviewError.message
          : "No se pudo revisar el candidato.",
        "error",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function reviewSelected(action: "approve" | "reject") {
    if (!selected.length) return;
    if (action === "reject" && !rejectReason.trim()) {
      onNotify("Escribe un motivo antes de rechazar en bloque.", "error");
      return;
    }
    setSubmitting(true);
    try {
      await client.bulkReviewDiscoveryCandidates({
        action,
        candidate_ids: selected,
        reason: action === "reject" ? rejectReason.trim() : undefined,
      });
      onNotify(
        `${selected.length} candidato${selected.length === 1 ? "" : "s"} revisado${selected.length === 1 ? "" : "s"}.`,
        "success",
      );
      await load();
    } catch (reviewError) {
      onNotify(
        reviewError instanceof Error
          ? reviewError.message
          : "No se pudo completar la revisión en bloque.",
        "error",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (loading && !sources.length) {
    return <LoadingBlock label="Consultando fuentes y candidatos" />;
  }

  return (
    <div className="view-stack">
      {error ? <div className="inline-error">{error}</div> : null}
      <section className="view-heading">
        <div>
          <p className="section-kicker">Catálogo controlado</p>
          <h2>Descubrimiento de productos</h2>
          <p>
            Scrapy revisa sitemaps públicos ya aprobados. Cada vuelta consulta
            como máximo el índice y un archivo de productos; encontrar una URL
            no la activa hasta que tú la apruebes.
          </p>
        </div>
      </section>

      <section className="discovery-source-grid">
        {sources.map((source) => (
          <article className="surface discovery-source-card" key={source.id}>
            <header>
              <div>
                <p className="section-kicker">{source.source_type}</p>
                <h3>{titleCase(source.store_slug)}</h3>
              </div>
              <StatusPill tone={statusTone(source.last_status)}>
                {titleCase(source.last_status)}
              </StatusPill>
            </header>
            <div className="discovery-source-card__metrics">
              <span>
                Pendientes
                <strong>{source.candidate_counts.pending ?? 0}</strong>
              </span>
              <span>
                Por vuelta
                <strong>{source.max_candidates_per_run}</strong>
              </span>
              <span>
                Documentos
                <strong>{source.max_documents_per_run}</strong>
              </span>
              <span>
                Aprobaciones/día
                <strong>{source.daily_approval_limit}</strong>
              </span>
            </div>
            <p>{source.notes}</p>
            <small>
              Próxima: {formatDateTime(source.next_run_at)} · última{" "}
              {formatRelativeTime(source.last_finished_at)}
            </small>
            {source.last_error ? (
              <div className="form-error">{source.last_error}</div>
            ) : null}
            <footer>
              <a href={source.source_url} rel="noreferrer" target="_blank">
                Ver fuente <ExternalLinkIcon />
              </a>
              <Button
                disabled={submitting || !source.enabled}
                onClick={() => void scheduleSource(source)}
                tone="secondary"
                type="button"
              >
                <RadarIcon />
                Programar
              </Button>
            </footer>
          </article>
        ))}
      </section>

      <section className="surface discovery-candidates">
        <header className="surface__header">
          <div>
            <p className="section-kicker">Revisión humana</p>
            <h2>Candidatos encontrados</h2>
          </div>
          <span className="selection-count">{selected.length}/20</span>
        </header>

        <form
          className="discovery-toolbar"
          onSubmit={(event) => {
            event.preventDefault();
            setAppliedSearch(search.trim());
          }}
        >
          <label>
            Estado
            <select
              onChange={(event) =>
                setCandidateStatus(event.target.value as DiscoveryCandidateStatus)
              }
              value={candidateStatus}
            >
              {candidateStatuses.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Tienda
            <select onChange={(event) => setStore(event.target.value)} value={store}>
              <option value="">Todas</option>
              {sources.map((source) => (
                <option key={source.id} value={source.store_slug}>
                  {titleCase(source.store_slug)}
                </option>
              ))}
            </select>
          </label>
          <label className="search-field">
            <SearchIcon />
            <input
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Buscar etiqueta o URL"
              value={search}
            />
          </label>
          <Button tone="secondary" type="submit">
            Buscar
          </Button>
        </form>

        {candidateStatus === "pending" ? (
          <div className="discovery-review-bar">
            <label>
              Motivo para rechazar
              <input
                maxLength={500}
                onChange={(event) => setRejectReason(event.target.value)}
                placeholder="Ej.: variante no prioritaria"
                value={rejectReason}
              />
            </label>
            <Button
              disabled={!selected.length || submitting}
              onClick={() => void reviewSelected("approve")}
              type="button"
            >
              <CheckIcon />
              Aprobar seleccionados
            </Button>
            <Button
              disabled={!selected.length || submitting || !rejectReason.trim()}
              onClick={() => void reviewSelected("reject")}
              tone="danger"
              type="button"
            >
              Rechazar seleccionados
            </Button>
          </div>
        ) : null}

        {candidates.length ? (
          <div className="data-table-wrap">
            <table className="data-table discovery-table">
              <thead>
                <tr>
                  <th>
                    <input
                      aria-label="Seleccionar pendientes visibles"
                      checked={
                        Boolean(pendingIds.length) &&
                        pendingIds.every((id) => selected.includes(id))
                      }
                      disabled={!pendingIds.length}
                      onChange={(event) =>
                        setSelected(event.target.checked ? pendingIds.slice(0, 20) : [])
                      }
                      type="checkbox"
                    />
                  </th>
                  <th>Producto</th>
                  <th>Tienda</th>
                  <th>Visto</th>
                  <th>Estado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((candidate) => (
                  <tr key={candidate.id}>
                    <td>
                      <input
                        aria-label={`Seleccionar ${candidate.label}`}
                        checked={selected.includes(candidate.id)}
                        disabled={candidate.status !== "pending"}
                        onChange={() =>
                          setSelected((current) =>
                            current.includes(candidate.id)
                              ? current.filter((id) => id !== candidate.id)
                              : current.length < 20
                                ? [...current, candidate.id]
                                : current,
                          )
                        }
                        type="checkbox"
                      />
                    </td>
                    <td>
                      <strong>{candidate.label}</strong>
                      <a
                        href={candidate.canonical_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        {candidate.canonical_url}
                      </a>
                      {candidate.reason ? <small>{candidate.reason}</small> : null}
                    </td>
                    <td>{titleCase(candidate.store_slug)}</td>
                    <td title={formatDateTime(candidate.last_seen_at)}>
                      {formatRelativeTime(candidate.last_seen_at)}
                    </td>
                    <td>
                      <StatusPill tone={statusTone(candidate.status)}>
                        {titleCase(candidate.status)}
                      </StatusPill>
                    </td>
                    <td>
                      {candidate.status === "pending" ? (
                        <div className="table-actions">
                          <Button
                            disabled={submitting}
                            onClick={() => void reviewOne(candidate, "approve")}
                            tone="ghost"
                            type="button"
                          >
                            Aprobar
                          </Button>
                          <Button
                            disabled={submitting || !rejectReason.trim()}
                            onClick={() => void reviewOne(candidate, "reject")}
                            tone="danger"
                            type="button"
                          >
                            Rechazar
                          </Button>
                        </div>
                      ) : (
                        <span className="muted-text">
                          {candidate.reviewed_by ?? "Automático"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            action={<Button onClick={() => void load()}>Actualizar</Button>}
            description="Cambia los filtros o programa una fuente para el próximo ciclo."
            title="No hay candidatos en esta vista"
          />
        )}
      </section>

      <section className="surface">
        <header className="surface__header">
          <div>
            <p className="section-kicker">Auditoría</p>
            <h2>Ejecuciones recientes</h2>
          </div>
        </header>
        {runs.length ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Tienda</th>
                  <th>Inicio</th>
                  <th>Documentos</th>
                  <th>Nuevos</th>
                  <th>Duplicados</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>{titleCase(run.store_slug)}</td>
                    <td>{formatDateTime(run.started_at)}</td>
                    <td>{run.document_count}</td>
                    <td>{run.new_count}</td>
                    <td>{run.duplicate_count}</td>
                    <td>
                      <StatusPill tone={statusTone(run.status)}>
                        {titleCase(run.status)}
                      </StatusPill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            description="El worker todavía no ha ejecutado una fuente."
            title="Sin ejecuciones de descubrimiento"
          />
        )}
      </section>
    </div>
  );
}
