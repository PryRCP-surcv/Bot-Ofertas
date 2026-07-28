const dateTimeFormatter = new Intl.DateTimeFormat("es-PE", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "America/Lima",
});

const relativeFormatter = new Intl.RelativeTimeFormat("es-PE", {
  numeric: "auto",
});

const currencyFormatters = new Map<string, Intl.NumberFormat>();

export function formatCurrency(
  value: number | string | null | undefined,
  currency = "PEN",
): string {
  if (value === null || value === undefined || value === "") {
    return "Sin precio";
  }

  const numericValue = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numericValue)) {
    return "Sin precio";
  }

  const formatter =
    currencyFormatters.get(currency) ??
    new Intl.NumberFormat("es-PE", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    });
  currencyFormatters.set(currency, formatter);
  return formatter.format(numericValue);
}

export function formatPercent(
  value: number | string | null | undefined,
): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const numericValue = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numericValue)
    ? `${Math.round(numericValue)}%`
    : "—";
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "Sin registros";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Fecha desconocida" : dateTimeFormatter.format(date);
}

export function formatRelativeTime(
  value: string | null | undefined,
  now = new Date(),
): string {
  if (!value) {
    return "Nunca";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Fecha desconocida";
  }
  const seconds = Math.round((date.getTime() - now.getTime()) / 1_000);
  const absoluteSeconds = Math.abs(seconds);
  if (absoluteSeconds < 60) {
    return relativeFormatter.format(seconds, "second");
  }
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) {
    return relativeFormatter.format(minutes, "minute");
  }
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) {
    return relativeFormatter.format(hours, "hour");
  }
  const days = Math.round(hours / 24);
  return relativeFormatter.format(days, "day");
}

export function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\p{L}/gu, (letter) => letter.toUpperCase());
}

export function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}

export function makeIdempotencyKey(prefix: string): string {
  const randomPart =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${randomPart}`;
}
