"use client";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import { ApiClient } from "@/lib/api";
import {
  formatCurrency,
  formatDateTime,
  makeIdempotencyKey,
} from "@/lib/format";
import type {
  CommercialSummaryRead,
  LaunchChecklistItemRead,
  PaymentMethod,
  PaymentRead,
  SubscriberRead,
  SubscriberStatus,
  TelegramMembershipStatus,
} from "@/lib/types";

import {
  CheckIcon,
  PlusIcon,
  SearchIcon,
  UsersIcon,
} from "../components/icons";
import {
  Button,
  EmptyState,
  LoadingBlock,
  Modal,
  StatusPill,
} from "../components/ui";

const statusLabels: Record<SubscriberStatus, string> = {
  trial: "Prueba",
  active: "Activo",
  expired: "Vencido",
  suspended: "Suspendido",
};

const membershipLabels: Record<TelegramMembershipStatus, string> = {
  pending: "Pendiente de agregar",
  in_group: "Dentro del grupo",
  removed: "Retirado",
};

const methodLabels: Record<PaymentMethod, string> = {
  yape: "Yape",
  plin: "Plin",
  bank_transfer: "Transferencia",
  cash: "Efectivo",
  other: "Otro",
};

function statusTone(
  value: SubscriberStatus,
): "success" | "warning" | "danger" | "info" {
  if (value === "active") return "success";
  if (value === "trial") return "info";
  if (value === "expired") return "warning";
  return "danger";
}

export function SubscribersView({
  client,
  onNotify,
  refreshNonce,
}: {
  client: ApiClient;
  onNotify: (message: string, tone: "success" | "error") => void;
  refreshNonce: number;
}) {
  const [summary, setSummary] = useState<CommercialSummaryRead | null>(null);
  const [subscribers, setSubscribers] = useState<SubscriberRead[]>([]);
  const [checklist, setChecklist] = useState<LaunchChecklistItemRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<SubscriberStatus | "">("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<SubscriberRead | null>(null);
  const [paying, setPaying] = useState<SubscriberRead | null>(null);
  const [payments, setPayments] = useState<PaymentRead[]>([]);
  const [saving, setSaving] = useState(false);
  const [checklistBusy, setChecklistBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [summaryResponse, subscriberResponse, checklistResponse] =
        await Promise.all([
          client.getCommercialSummary(),
          client.listSubscribers({ limit: 100 }),
          client.getLaunchChecklist(),
        ]);
      setSummary(summaryResponse.data);
      setSubscribers(subscriberResponse.data.items);
      setChecklist(checklistResponse.data);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "No se pudo consultar la administración comercial.",
      );
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load, refreshNonce]);

  const visibleSubscribers = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("es-PE");
    return subscribers.filter((item) => {
      if (statusFilter && item.status !== statusFilter) return false;
      if (!term) return true;
      return [
        item.full_name,
        item.telegram_username,
        item.email ?? "",
        item.phone ?? "",
      ].some((value) => value.toLocaleLowerCase("es-PE").includes(term));
    });
  }, [search, statusFilter, subscribers]);

  async function toggleChecklist(item: LaunchChecklistItemRead) {
    setChecklistBusy(item.item_key);
    try {
      const response = await client.updateLaunchChecklistItem(item.item_key, {
        completed: !item.completed,
      });
      setChecklist((current) =>
        current.map((candidate) =>
          candidate.item_key === item.item_key ? response.data : candidate,
        ),
      );
      await refreshSummary();
    } catch (updateError) {
      onNotify(
        updateError instanceof Error
          ? updateError.message
          : "No se pudo actualizar la lista de lanzamiento.",
        "error",
      );
    } finally {
      setChecklistBusy(null);
    }
  }

  async function refreshSummary() {
    const response = await client.getCommercialSummary();
    setSummary(response.data);
  }

  async function openPayment(subscriber: SubscriberRead) {
    setPaying(subscriber);
    setPayments([]);
    try {
      const response = await client.listSubscriberPayments(subscriber.id);
      setPayments(response.data);
    } catch (paymentError) {
      onNotify(
        paymentError instanceof Error
          ? paymentError.message
          : "No se pudo consultar el historial de pagos.",
        "error",
      );
    }
  }

  if (loading && !summary) {
    return <LoadingBlock label="Preparando la administración comercial" />;
  }

  if (error && !summary) {
    return (
      <EmptyState
        action={<Button onClick={() => void load()}>Reintentar</Button>}
        description={error}
        title="No se pudo abrir la beta comercial"
      />
    );
  }

  if (!summary) return null;

  return (
    <div className="view-stack">
      {error ? <div className="inline-error">{error}</div> : null}

      <section className="commercial-hero">
        <div>
          <p className="section-kicker">Preparación del primer lanzamiento</p>
          <h2>
            {summary.launch_ready
              ? "La operación está lista para el grupo piloto"
              : "Construye una beta pequeña y medible"}
          </h2>
          <p>
            Registra pagos confirmados fuera del sistema, controla vigencias y
            deja evidencia de quién debe entrar o salir del grupo privado.
          </p>
          <StatusPill tone={summary.launch_ready ? "success" : "warning"}>
            {summary.launch_ready
              ? "Lista de lanzamiento completada"
              : `${summary.checklist_completed}/${summary.checklist_required} controles obligatorios`}
          </StatusPill>
        </div>
        <aside>
          <strong>Importante para tus clientes</strong>
          <p>
            Los precios, el stock y las condiciones pertenecen a cada tienda.
            Una oferta puede cambiar, agotarse o ser cancelada. El bot informa;
            no compra ni garantiza la venta.
          </p>
        </aside>
      </section>

      <section className="commercial-metrics" aria-label="Resumen comercial">
        <CommercialMetric
          detail={`${summary.trial_subscribers} en prueba`}
          label="Suscriptores vigentes"
          value={summary.active_subscribers + summary.trial_subscribers}
        />
        <CommercialMetric
          attention={summary.expiring_within_7_days > 0}
          detail="durante los próximos 7 días"
          label="Próximos a vencer"
          value={summary.expiring_within_7_days}
        />
        <CommercialMetric
          detail={`${formatCurrency(summary.confirmed_revenue_total_pen)} acumulado`}
          label="Ingresos del mes"
          value={formatCurrency(summary.confirmed_revenue_month_pen)}
        />
        <CommercialMetric
          attention={summary.pending_group_access > 0}
          detail={`${summary.members_in_group} miembros vigentes dentro`}
          label="Accesos pendientes"
          value={summary.pending_group_access}
        />
        <CommercialMetric
          detail={`${summary.alerts_sent_30_days} durante los últimos 30 días`}
          label="Alertas en 7 días"
          value={summary.alerts_sent_7_days}
        />
      </section>

      <section className="commercial-layout">
        <article className="panel-card subscriber-catalog">
          <div className="panel-card__header subscriber-header">
            <div>
              <p className="section-kicker">Control manual y auditable</p>
              <h2>Suscriptores</h2>
            </div>
            <Button onClick={() => setCreateOpen(true)}>
              <PlusIcon />
              Nuevo suscriptor
            </Button>
          </div>

          <div className="subscriber-toolbar">
            <label className="search-field">
              <SearchIcon />
              <span className="sr-only">Buscar suscriptor</span>
              <input
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Nombre, Telegram, correo o teléfono"
                type="search"
                value={search}
              />
            </label>
            <label>
              <span>Estado</span>
              <select
                onChange={(event) =>
                  setStatusFilter(event.target.value as SubscriberStatus | "")
                }
                value={statusFilter}
              >
                <option value="">Todos</option>
                <option value="trial">Prueba</option>
                <option value="active">Activos</option>
                <option value="expired">Vencidos</option>
                <option value="suspended">Suspendidos</option>
              </select>
            </label>
          </div>

          {visibleSubscribers.length ? (
            <div className="data-table-wrap">
              <table className="data-table subscriber-table">
                <thead>
                  <tr>
                    <th>Persona</th>
                    <th>Vigencia</th>
                    <th>Telegram</th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleSubscribers.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <div className="table-product">
                          <strong>{item.full_name}</strong>
                          <span>@{item.telegram_username}</span>
                          <small>{item.email || item.phone || "Sin contacto adicional"}</small>
                        </div>
                      </td>
                      <td>
                        <StatusPill tone={statusTone(item.status)}>
                          {statusLabels[item.status]}
                        </StatusPill>
                        <small className="table-note">
                          {item.status === "expired"
                            ? "Acceso vencido"
                            : `${item.days_remaining} días · ${formatDateTime(item.expires_at)}`}
                        </small>
                      </td>
                      <td>
                        <strong>{membershipLabels[item.telegram_membership_status]}</strong>
                        {item.status === "expired" &&
                        item.telegram_membership_status === "in_group" ? (
                          <small className="table-warning">Retiro pendiente</small>
                        ) : null}
                      </td>
                      <td>
                        <div className="table-actions subscriber-actions">
                          <Button
                            onClick={() => void openPayment(item)}
                            tone="secondary"
                          >
                            Registrar pago
                          </Button>
                          <Button onClick={() => setEditing(item)} tone="ghost">
                            Gestionar
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              action={
                subscribers.length === 0 ? (
                  <Button onClick={() => setCreateOpen(true)}>
                    Registrar primera persona
                  </Button>
                ) : undefined
              }
              description={
                subscribers.length === 0
                  ? "Comienza con un grupo piloto reducido y conocido."
                  : "Prueba con otro término o estado."
              }
              title={
                subscribers.length === 0
                  ? "Aún no hay suscriptores"
                  : "No hay coincidencias"
              }
            />
          )}
        </article>

        <aside className="panel-card launch-checklist">
          <div className="panel-card__header">
            <div>
              <p className="section-kicker">Antes de aceptar pagos</p>
              <h2>Lista de lanzamiento</h2>
            </div>
          </div>
          <div className="checklist-progress">
            <span>
              {summary.checklist_completed} de {summary.checklist_required} obligatorios
            </span>
            <progress
              max={Math.max(summary.checklist_required, 1)}
              value={summary.checklist_completed}
            />
          </div>
          <div className="launch-checklist__items">
            {checklist.map((item) => (
              <button
                className={item.completed ? "completed" : ""}
                disabled={checklistBusy === item.item_key}
                key={item.item_key}
                onClick={() => void toggleChecklist(item)}
                type="button"
              >
                <span className="checklist-mark">
                  {item.completed ? <CheckIcon /> : item.position}
                </span>
                <span>
                  <strong>
                    {item.title}
                    {!item.required ? <small> Opcional</small> : null}
                  </strong>
                  <small>{item.description}</small>
                </span>
              </button>
            ))}
          </div>
        </aside>
      </section>

      <CreateSubscriberModal
        client={client}
        onClose={() => setCreateOpen(false)}
        onCreated={async (created) => {
          setCreateOpen(false);
          setSubscribers((current) => [created, ...current]);
          await refreshSummary();
          onNotify("Suscriptor registrado para la beta.", "success");
        }}
        onNotify={onNotify}
        open={createOpen}
        saving={saving}
        setSaving={setSaving}
      />
      <ManageSubscriberModal
        client={client}
        onClose={() => setEditing(null)}
        onNotify={onNotify}
        onUpdated={async (updated) => {
          setEditing(null);
          setSubscribers((current) =>
            current.map((item) => (item.id === updated.id ? updated : item)),
          );
          await refreshSummary();
          onNotify("Suscriptor actualizado.", "success");
        }}
        saving={saving}
        setSaving={setSaving}
        subscriber={editing}
      />
      <PaymentModal
        client={client}
        onClose={() => setPaying(null)}
        onNotify={onNotify}
        onRecorded={async (updated, payment) => {
          setSubscribers((current) =>
            current.map((item) => (item.id === updated.id ? updated : item)),
          );
          setPaying(updated);
          setPayments((current) => [payment, ...current]);
          await refreshSummary();
          onNotify("Pago registrado y vigencia renovada.", "success");
        }}
        payments={payments}
        saving={saving}
        setSaving={setSaving}
        subscriber={paying}
      />
    </div>
  );
}

function CommercialMetric({
  attention = false,
  detail,
  label,
  value,
}: {
  attention?: boolean;
  detail: string;
  label: string;
  value: number | string;
}) {
  return (
    <article className={attention ? "commercial-metric attention" : "commercial-metric"}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function CreateSubscriberModal({
  client,
  onClose,
  onCreated,
  onNotify,
  open,
  saving,
  setSaving,
}: {
  client: ApiClient;
  onClose: () => void;
  onCreated: (subscriber: SubscriberRead) => Promise<void>;
  onNotify: (message: string, tone: "success" | "error") => void;
  open: boolean;
  saving: boolean;
  setSaving: (value: boolean) => void;
}) {
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    try {
      const response = await client.createSubscriber({
        full_name: String(form.get("full_name") ?? ""),
        telegram_username: String(form.get("telegram_username") ?? ""),
        email: String(form.get("email") ?? "") || null,
        phone: String(form.get("phone") ?? "") || null,
        status: String(form.get("status") ?? "trial") as "trial" | "active",
        duration_days: Number(form.get("duration_days") ?? 7),
        notes: String(form.get("notes") ?? "") || null,
      });
      event.currentTarget.reset();
      await onCreated(response.data);
    } catch (createError) {
      onNotify(
        createError instanceof Error
          ? createError.message
          : "No se pudo registrar al suscriptor.",
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      description="El acceso y el cobro se confirmarán manualmente durante la beta."
      onClose={onClose}
      open={open}
      title="Registrar suscriptor"
    >
      <form className="form-grid" onSubmit={(event) => void submit(event)}>
        <label className="field">
          <span>Nombre completo</span>
          <input maxLength={200} name="full_name" required />
        </label>
        <label className="field">
          <span>Usuario de Telegram</span>
          <input
            autoCapitalize="none"
            maxLength={33}
            minLength={5}
            name="telegram_username"
            placeholder="@usuario"
            required
          />
        </label>
        <label className="field">
          <span>Correo opcional</span>
          <input maxLength={320} name="email" type="email" />
        </label>
        <label className="field">
          <span>Teléfono opcional</span>
          <input maxLength={40} name="phone" type="tel" />
        </label>
        <label className="field">
          <span>Tipo inicial</span>
          <select defaultValue="trial" name="status">
            <option value="trial">Prueba</option>
            <option value="active">Activo</option>
          </select>
        </label>
        <label className="field">
          <span>Duración inicial</span>
          <select defaultValue="7" name="duration_days">
            <option value="3">3 días</option>
            <option value="7">7 días</option>
            <option value="15">15 días</option>
            <option value="30">30 días</option>
          </select>
        </label>
        <label className="field field--wide">
          <span>Notas internas</span>
          <textarea maxLength={2000} name="notes" rows={3} />
        </label>
        <div className="form-actions">
          <Button onClick={onClose} tone="ghost" type="button">
            Cancelar
          </Button>
          <Button disabled={saving} type="submit">
            {saving ? "Guardando" : "Registrar"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ManageSubscriberModal({
  client,
  onClose,
  onNotify,
  onUpdated,
  saving,
  setSaving,
  subscriber,
}: {
  client: ApiClient;
  onClose: () => void;
  onNotify: (message: string, tone: "success" | "error") => void;
  onUpdated: (subscriber: SubscriberRead) => Promise<void>;
  saving: boolean;
  setSaving: (value: boolean) => void;
  subscriber: SubscriberRead | null;
}) {
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!subscriber) return;
    const form = new FormData(event.currentTarget);
    setSaving(true);
    try {
      const response = await client.updateSubscriber(
        subscriber.id,
        {
          full_name: String(form.get("full_name") ?? ""),
          email: String(form.get("email") ?? "") || null,
          phone: String(form.get("phone") ?? "") || null,
          status: String(form.get("status") ?? "trial") as
            | "trial"
            | "active"
            | "suspended",
          telegram_membership_status: String(
            form.get("telegram_membership_status") ?? "pending",
          ) as TelegramMembershipStatus,
          notes: String(form.get("notes") ?? "") || null,
        },
        { etag: `"${subscriber.version}"` },
      );
      await onUpdated(response.data);
    } catch (updateError) {
      onNotify(
        updateError instanceof Error
          ? updateError.message
          : "No se pudo actualizar al suscriptor.",
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      description={
        subscriber
          ? `Gestionando a @${subscriber.telegram_username}. Los cambios de acceso reflejan acciones manuales en Telegram.`
          : undefined
      }
      onClose={onClose}
      open={subscriber !== null}
      title="Gestionar suscriptor"
    >
      {subscriber ? (
        <form className="form-grid" onSubmit={(event) => void submit(event)}>
          <label className="field">
            <span>Nombre completo</span>
            <input
              defaultValue={subscriber.full_name}
              maxLength={200}
              name="full_name"
              required
            />
          </label>
          <label className="field">
            <span>Estado comercial</span>
            <select
              defaultValue={
                subscriber.stored_status === "expired"
                  ? "active"
                  : subscriber.stored_status
              }
              name="status"
            >
              <option value="trial">Prueba</option>
              <option value="active">Activo</option>
              <option value="suspended">Suspendido</option>
            </select>
          </label>
          <label className="field">
            <span>Estado en Telegram</span>
            <select
              defaultValue={subscriber.telegram_membership_status}
              name="telegram_membership_status"
            >
              <option value="pending">Pendiente de agregar</option>
              <option value="in_group">Dentro del grupo</option>
              <option value="removed">Retirado</option>
            </select>
          </label>
          <label className="field">
            <span>Vencimiento</span>
            <input
              disabled
              value={formatDateTime(subscriber.expires_at)}
            />
            <small>Registra un pago para extender la vigencia.</small>
          </label>
          <label className="field">
            <span>Correo</span>
            <input
              defaultValue={subscriber.email ?? ""}
              maxLength={320}
              name="email"
              type="email"
            />
          </label>
          <label className="field">
            <span>Teléfono</span>
            <input
              defaultValue={subscriber.phone ?? ""}
              maxLength={40}
              name="phone"
              type="tel"
            />
          </label>
          <label className="field field--wide">
            <span>Notas internas</span>
            <textarea
              defaultValue={subscriber.notes ?? ""}
              maxLength={2000}
              name="notes"
              rows={3}
            />
          </label>
          <div className="manual-access-note field--wide">
            <UsersIcon />
            <p>
              Después de cambiar este estado, agrega o retira manualmente a la
              persona en Telegram. El sistema no expulsa miembros por sí solo.
            </p>
          </div>
          <div className="form-actions">
            <Button onClick={onClose} tone="ghost" type="button">
              Cancelar
            </Button>
            <Button disabled={saving} type="submit">
              {saving ? "Guardando" : "Guardar cambios"}
            </Button>
          </div>
        </form>
      ) : null}
    </Modal>
  );
}

function PaymentModal({
  client,
  onClose,
  onNotify,
  onRecorded,
  payments,
  saving,
  setSaving,
  subscriber,
}: {
  client: ApiClient;
  onClose: () => void;
  onNotify: (message: string, tone: "success" | "error") => void;
  onRecorded: (
    subscriber: SubscriberRead,
    payment: PaymentRead,
  ) => Promise<void>;
  payments: PaymentRead[];
  saving: boolean;
  setSaving: (value: boolean) => void;
  subscriber: SubscriberRead | null;
}) {
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!subscriber) return;
    const form = new FormData(event.currentTarget);
    setSaving(true);
    try {
      const response = await client.recordSubscriberPayment(
        subscriber.id,
        {
          amount: String(form.get("amount") ?? ""),
          method: String(form.get("method") ?? "yape") as PaymentMethod,
          reference: String(form.get("reference") ?? "") || null,
          renewal_days: Number(form.get("renewal_days") ?? 30),
          notes: String(form.get("notes") ?? "") || null,
        },
        { idempotencyKey: makeIdempotencyKey("beta-payment") },
      );
      event.currentTarget.reset();
      await onRecorded(
        response.data.subscriber,
        response.data.payment,
      );
    } catch (paymentError) {
      onNotify(
        paymentError instanceof Error
          ? paymentError.message
          : "No se pudo registrar el pago.",
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      description={
        subscriber
          ? `El pago ya debe estar confirmado externamente. La renovación comenzará desde ${formatDateTime(subscriber.expires_at)} o desde hoy si ya venció.`
          : undefined
      }
      onClose={onClose}
      open={subscriber !== null}
      title="Registrar pago y renovar"
    >
      {subscriber ? (
        <div className="payment-modal-layout">
          <form className="form-grid" onSubmit={(event) => void submit(event)}>
            <label className="field">
              <span>Monto confirmado (PEN)</span>
              <input
                min="0.01"
                name="amount"
                placeholder="10.00"
                required
                step="0.01"
                type="number"
              />
            </label>
            <label className="field">
              <span>Método</span>
              <select defaultValue="yape" name="method">
                {Object.entries(methodLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Renovación</span>
              <select defaultValue="30" name="renewal_days">
                <option value="7">7 días</option>
                <option value="15">15 días</option>
                <option value="30">30 días</option>
                <option value="60">60 días</option>
                <option value="90">90 días</option>
              </select>
            </label>
            <label className="field">
              <span>Referencia opcional</span>
              <input maxLength={200} name="reference" />
            </label>
            <label className="field field--wide">
              <span>Notas internas</span>
              <textarea maxLength={2000} name="notes" rows={2} />
            </label>
            <div className="form-actions">
              <Button onClick={onClose} tone="ghost" type="button">
                Cerrar
              </Button>
              <Button disabled={saving} type="submit">
                {saving ? "Registrando" : "Confirmar pago"}
              </Button>
            </div>
          </form>

          <section className="payment-history">
            <h3>Historial</h3>
            {payments.length ? (
              <div>
                {payments.map((payment) => (
                  <article key={payment.id}>
                    <span>
                      <strong>{formatCurrency(payment.amount)}</strong>
                      <small>{methodLabels[payment.method]}</small>
                    </span>
                    <span>
                      <strong>{payment.renewal_days} días</strong>
                      <small>{formatDateTime(payment.paid_at)}</small>
                    </span>
                  </article>
                ))}
              </div>
            ) : (
              <p>Aún no tiene pagos registrados.</p>
            )}
          </section>
        </div>
      ) : null}
    </Modal>
  );
}
