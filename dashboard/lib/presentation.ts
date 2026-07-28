import type {
  CrawlJobStatus,
  CrawlRunStatus,
  DealClassification,
  NotificationStatus,
} from "./types";

export type Tone = "success" | "warning" | "danger" | "info" | "neutral";

export const classificationLabels: Record<DealClassification, string> = {
  none: "Sin clasificación",
  good_deal: "Buena oferta",
  exceptional_deal: "Oferta excepcional",
  possible_price_error: "Posible error de precio",
};

export const classificationTones: Record<DealClassification, Tone> = {
  none: "neutral",
  good_deal: "info",
  exceptional_deal: "success",
  possible_price_error: "danger",
};

export const notificationLabels: Record<NotificationStatus, string> = {
  not_applicable: "No aplica",
  awaiting_confirmation: "Espera confirmación",
  pending: "Pendiente",
  suppressed: "Suprimida",
  retrying: "Reintentando",
  sent: "Enviada",
  failed: "Fallida",
  superseded: "Reemplazada",
};

export const jobStatusLabels: Record<CrawlJobStatus, string> = {
  queued: "En cola",
  running: "Ejecutándose",
  retrying: "Reintentando",
  succeeded: "Completado",
  partial: "Parcial",
  failed: "Fallido",
  cancelled: "Cancelado",
};

export const runStatusLabels: Record<CrawlRunStatus, string> = {
  running: "Ejecutándose",
  succeeded: "Completada",
  partial: "Parcial",
  failed: "Fallida",
  cancelled: "Cancelada",
};

export function operationalTone(status: string): Tone {
  const normalized = status.toLowerCase();
  if (["healthy", "ready", "ok", "succeeded"].includes(normalized)) {
    return "success";
  }
  if (["paused", "partial", "retrying", "queued", "running"].includes(normalized)) {
    return "warning";
  }
  if (["failed", "blocked", "disabled", "unavailable"].includes(normalized)) {
    return "danger";
  }
  return "neutral";
}

export function jobTone(status: CrawlJobStatus | CrawlRunStatus): Tone {
  switch (status) {
    case "succeeded":
      return "success";
    case "running":
    case "queued":
    case "retrying":
    case "partial":
      return "warning";
    case "failed":
      return "danger";
    default:
      return "neutral";
  }
}
