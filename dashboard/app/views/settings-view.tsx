"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { ApiClient, ApiError } from "@/lib/api";
import { makeIdempotencyKey, shortId } from "@/lib/format";
import type {
  DecimalValue,
  RuntimePolicyPatch,
  RuntimePolicyRead,
} from "@/lib/types";

import { Button, EmptyState, LoadingBlock, StatusPill } from "../components/ui";

type EditableSetting = keyof RuntimePolicyPatch;
type SettingsForm = Record<EditableSetting, string | boolean>;

const editableFields: EditableSetting[] = [
  "scheduler_poll_seconds",
  "detection_history_limit",
  "detection_history_days",
  "minimum_history_samples",
  "equivalent_max_age_hours",
  "equivalent_limit",
  "minimum_equivalent_samples",
  "possible_error_minimum_corroborating_signals",
  "possible_error_minimum_confidence",
  "confirmation_required",
  "confirmation_max_age_minutes",
  "confirmation_price_tolerance_percent",
  "confirmation_confidence_bonus",
  "minimum_alert_confidence",
  "good_deal_percent",
  "exceptional_deal_percent",
  "possible_price_error_percent",
  "alert_cooldown_hours",
  "alert_significant_improvement_percent",
  "notification_lease_seconds",
  "notification_max_attempts",
  "notification_retry_base_seconds",
  "telegram_enabled",
];

const booleanFields = new Set<EditableSetting>([
  "confirmation_required",
  "telegram_enabled",
]);

function settingsToForm(settings: RuntimePolicyRead): SettingsForm {
  return Object.fromEntries(
    editableFields.map((field) => [
      field,
      booleanFields.has(field)
        ? Boolean(settings[field as keyof RuntimePolicyRead])
        : String(settings[field as keyof RuntimePolicyRead]),
    ]),
  ) as SettingsForm;
}

function numberValue(value: string | boolean): number {
  return typeof value === "boolean" ? Number(value) : Number(value);
}

function buildPatch(
  form: SettingsForm,
  original: RuntimePolicyRead,
): RuntimePolicyPatch {
  const patch: RuntimePolicyPatch = {};
  for (const field of editableFields) {
    if (booleanFields.has(field)) {
      const next = Boolean(form[field]);
      if (next !== original[field as keyof RuntimePolicyRead]) {
        (patch as Record<string, unknown>)[field] = next;
      }
      continue;
    }

    const next = numberValue(form[field]);
    const previous = Number(
      original[field as keyof RuntimePolicyRead] as DecimalValue,
    );
    if (Number.isFinite(next) && next !== previous) {
      (patch as Record<string, unknown>)[field] = next;
    }
  }
  return patch;
}

export function SettingsView({
  client,
  onNotify,
  refreshNonce,
}: {
  client: ApiClient;
  onNotify: (message: string, tone: "success" | "error") => void;
  refreshNonce: number;
}) {
  const [settings, setSettings] = useState<RuntimePolicyRead | null>(null);
  const [etag, setEtag] = useState<string | null>(null);
  const [form, setForm] = useState<SettingsForm | null>(null);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await client.getSettings();
      setSettings(response.data);
      setForm(settingsToForm(response.data));
      setEtag(
        response.meta.etag ?? `"${response.data.revision_id ?? 0}"`,
      );
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "No se pudo consultar la configuración.",
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

  const patch = useMemo(
    () => (form && settings ? buildPatch(form, settings) : {}),
    [form, settings],
  );
  const changedFields = Object.keys(patch);

  function setValue(field: EditableSetting, value: string | boolean) {
    setForm((current) => (current ? { ...current, [field]: value } : current));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings || !form || !etag || !changedFields.length) {
      return;
    }

    const good = numberValue(form.good_deal_percent);
    const exceptional = numberValue(form.exceptional_deal_percent);
    const possibleError = numberValue(form.possible_price_error_percent);
    if (!(good <= exceptional && exceptional <= possibleError)) {
      onNotify(
        "Los umbrales deben cumplir: buena oferta ≤ excepcional ≤ posible error.",
        "error",
      );
      return;
    }

    if (!reason.trim()) {
      onNotify("Escribe el motivo del cambio para conservar la auditoría.", "error");
      return;
    }

    if (
      !window.confirm(
        `Se guardarán ${changedFields.length} cambio(s) en una nueva revisión. ¿Continuar?`,
      )
    ) {
      return;
    }

    setSaving(true);
    try {
      const response = await client.updateSettings(patch, {
        etag,
        idempotencyKey: makeIdempotencyKey("panel-settings"),
        changeReason: reason.trim(),
      });
      setSettings(response.data);
      setForm(settingsToForm(response.data));
      setEtag(
        response.meta.etag ?? `"${response.data.revision_id ?? 0}"`,
      );
      setReason("");
      onNotify(
        `Configuración guardada en la revisión ${response.data.revision_id ?? 0}.`,
        "success",
      );
    } catch (saveError) {
      if (saveError instanceof ApiError && saveError.isStaleRevision) {
        onNotify(
          "La configuración cambió en otra operación. Recargamos la revisión vigente.",
          "error",
        );
        await load();
      } else {
        onNotify(
          saveError instanceof Error
            ? saveError.message
            : "No se pudo guardar la configuración.",
          "error",
        );
      }
    } finally {
      setSaving(false);
    }
  }

  if (loading && !settings) {
    return <LoadingBlock label="Cargando la política vigente" />;
  }

  if (error && !settings) {
    return (
      <EmptyState
        action={<Button onClick={() => void load()}>Reintentar</Button>}
        description={error}
        title="No se pudo cargar la configuración"
      />
    );
  }

  if (!settings || !form) {
    return null;
  }

  return (
    <form className="view-stack" onSubmit={save}>
      {error ? <div className="inline-error">{error}</div> : null}
      <section className="settings-intro">
        <div>
          <p className="section-kicker">Política auditable</p>
          <h2>Revisión {settings.revision_id ?? 0}</h2>
          <p>
            Detector {settings.detector_version} · huella{" "}
            <code>{shortId(settings.policy_fingerprint)}</code>
          </p>
        </div>
        <div className="settings-intro__status">
          <StatusPill
            tone={settings.telegram_configured ? "success" : "warning"}
          >
            Telegram{" "}
            {settings.telegram_configured ? "configurado" : "incompleto"}
          </StatusPill>
          <small>
            Token: {settings.telegram_token_configured ? "sí" : "no"} · Chat:{" "}
            {settings.telegram_chat_id_configured ? "sí" : "no"}
          </small>
        </div>
      </section>

      <section className="settings-grid">
        <SettingsSection
          description="Cuándo clasificar una caída como oportunidad y cuánta evidencia exigir."
          title="Detección de ofertas"
        >
          <NumberField
            label="Buena oferta desde (%)"
            max={99}
            min={0}
            onChange={(value) => setValue("good_deal_percent", value)}
            value={form.good_deal_percent}
          />
          <NumberField
            label="Oferta excepcional desde (%)"
            max={99}
            min={0}
            onChange={(value) => setValue("exceptional_deal_percent", value)}
            value={form.exceptional_deal_percent}
          />
          <NumberField
            label="Posible error desde (%)"
            max={99}
            min={0}
            onChange={(value) => setValue("possible_price_error_percent", value)}
            value={form.possible_price_error_percent}
          />
          <NumberField
            label="Confianza mínima para alertar"
            max={100}
            min={0}
            onChange={(value) => setValue("minimum_alert_confidence", value)}
            value={form.minimum_alert_confidence}
          />
          <NumberField
            label="Muestras históricas mínimas"
            max={100}
            min={1}
            onChange={(value) => setValue("minimum_history_samples", value)}
            value={form.minimum_history_samples}
          />
          <NumberField
            label="Confianza mínima para posible error"
            max={100}
            min={0}
            onChange={(value) =>
              setValue("possible_error_minimum_confidence", value)
            }
            value={form.possible_error_minimum_confidence}
          />
        </SettingsSection>

        <SettingsSection
          description="La segunda observación reduce falsos positivos antes de notificar."
          title="Confirmación"
        >
          <ToggleField
            checked={Boolean(form.confirmation_required)}
            label="Exigir confirmación"
            onChange={(value) => setValue("confirmation_required", value)}
          />
          <NumberField
            label="Ventana máxima (minutos)"
            max={10_080}
            min={30}
            onChange={(value) => setValue("confirmation_max_age_minutes", value)}
            value={form.confirmation_max_age_minutes}
          />
          <NumberField
            label="Tolerancia de precio (%)"
            max={99}
            min={0}
            onChange={(value) =>
              setValue("confirmation_price_tolerance_percent", value)
            }
            step="0.1"
            value={form.confirmation_price_tolerance_percent}
          />
          <NumberField
            label="Bono de confianza"
            max={100}
            min={0}
            onChange={(value) => setValue("confirmation_confidence_bonus", value)}
            value={form.confirmation_confidence_bonus}
          />
          <NumberField
            label="Señales para posible error"
            max={8}
            min={2}
            onChange={(value) =>
              setValue("possible_error_minimum_corroborating_signals", value)
            }
            value={form.possible_error_minimum_corroborating_signals}
          />
        </SettingsSection>

        <SettingsSection
          description="Frecuencia del proceso, tamaño del historial y comparación entre equivalentes."
          title="Ejecución e historial"
        >
          <NumberField
            hint="Cambiar este valor requiere reiniciar bot-ofertas run."
            label="Consulta del scheduler (segundos)"
            max={86_400}
            min={30}
            onChange={(value) => setValue("scheduler_poll_seconds", value)}
            value={form.scheduler_poll_seconds}
          />
          <NumberField
            label="Días de historial"
            max={3_650}
            min={30}
            onChange={(value) => setValue("detection_history_days", value)}
            value={form.detection_history_days}
          />
          <NumberField
            label="Máximo de observaciones"
            max={10_000}
            min={3}
            onChange={(value) => setValue("detection_history_limit", value)}
            value={form.detection_history_limit}
          />
          <NumberField
            label="Edad máxima de equivalentes (horas)"
            max={720}
            min={1}
            onChange={(value) => setValue("equivalent_max_age_hours", value)}
            value={form.equivalent_max_age_hours}
          />
          <NumberField
            label="Límite de equivalentes"
            max={100}
            min={2}
            onChange={(value) => setValue("equivalent_limit", value)}
            value={form.equivalent_limit}
          />
          <NumberField
            label="Equivalentes mínimos"
            max={20}
            min={1}
            onChange={(value) => setValue("minimum_equivalent_samples", value)}
            value={form.minimum_equivalent_samples}
          />
        </SettingsSection>

        <SettingsSection
          description="Controla duplicados, reintentos y el canal de Telegram sin exponer credenciales."
          title="Alertas"
        >
          <ToggleField
            checked={Boolean(form.telegram_enabled)}
            label="Habilitar Telegram"
            onChange={(value) => setValue("telegram_enabled", value)}
          />
          <NumberField
            label="Espera entre alertas (horas)"
            max={720}
            min={1}
            onChange={(value) => setValue("alert_cooldown_hours", value)}
            value={form.alert_cooldown_hours}
          />
          <NumberField
            label="Mejora para repetir alerta (%)"
            max={99}
            min={0}
            onChange={(value) =>
              setValue("alert_significant_improvement_percent", value)
            }
            step="0.1"
            value={form.alert_significant_improvement_percent}
          />
          <NumberField
            label="Intentos máximos"
            max={20}
            min={1}
            onChange={(value) => setValue("notification_max_attempts", value)}
            value={form.notification_max_attempts}
          />
          <NumberField
            label="Base de reintento (segundos)"
            max={86_400}
            min={30}
            onChange={(value) =>
              setValue("notification_retry_base_seconds", value)
            }
            value={form.notification_retry_base_seconds}
          />
          <NumberField
            label="Lease de notificación (segundos)"
            max={3_600}
            min={30}
            onChange={(value) => setValue("notification_lease_seconds", value)}
            value={form.notification_lease_seconds}
          />
        </SettingsSection>
      </section>

      <section className="settings-save surface">
        <label className="field">
          <span>Motivo del cambio</span>
          <input
            maxLength={2_000}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Ej.: Ajuste revisado de confianza"
            value={reason}
          />
          <small>Quedará guardado en el historial de revisiones.</small>
        </label>
        <div>
          <span>
            {changedFields.length
              ? `${changedFields.length} campo(s) modificado(s)`
              : "No hay cambios pendientes"}
          </span>
          <Button disabled={!changedFields.length || saving} type="submit">
            {saving ? "Guardando…" : "Guardar nueva revisión"}
          </Button>
        </div>
      </section>
    </form>
  );
}

function SettingsSection({
  children,
  description,
  title,
}: {
  children: React.ReactNode;
  description: string;
  title: string;
}) {
  return (
    <section className="surface settings-section">
      <header>
        <h3>{title}</h3>
        <p>{description}</p>
      </header>
      <div>{children}</div>
    </section>
  );
}

function NumberField({
  hint,
  label,
  max,
  min,
  onChange,
  step = "1",
  value,
}: {
  hint?: string;
  label: string;
  max: number;
  min: number;
  onChange: (value: string) => void;
  step?: string;
  value: string | boolean;
}) {
  return (
    <label className="field compact-field">
      <span>{label}</span>
      <input
        max={max}
        min={min}
        onChange={(event) => onChange(event.target.value)}
        required
        step={step}
        type="number"
        value={String(value)}
      />
      {hint ? <small>{hint}</small> : null}
    </label>
  );
}

function ToggleField({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="toggle-field">
      <span>{label}</span>
      <input
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
      <i aria-hidden="true" />
    </label>
  );
}
