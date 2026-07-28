"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { ApiClient, ApiError } from "@/lib/api";
import {
  formatCurrency,
  formatDateTime,
  formatRelativeTime,
  titleCase,
} from "@/lib/format";
import type {
  ObservationRead,
  ProductCreate,
  ProductPatch,
  ProductRead,
  StoreRead,
} from "@/lib/types";

import {
  ExternalLinkIcon,
  PlusIcon,
  SearchIcon,
} from "../components/icons";
import {
  Button,
  EmptyState,
  LoadingBlock,
  Modal,
  StatusPill,
} from "../components/ui";

type ProductFilter = "all" | "active" | "inactive" | "archived";

interface ProductFormState {
  active: boolean;
  checkIntervalMinutes: string;
  expectedBrand: string;
  expectedIsAccessory: boolean;
  expectedModel: string;
  expectedVariantText: string;
  label: string;
  url: string;
}

const emptyProductForm: ProductFormState = {
  active: true,
  checkIntervalMinutes: "60",
  expectedBrand: "",
  expectedIsAccessory: false,
  expectedModel: "",
  expectedVariantText: "",
  label: "",
  url: "",
};

function etagForVersion(version: number): string {
  return `"${version}"`;
}

function parseVariantText(value: string): Record<string, string> {
  const variant: Record<string, string> = {};
  for (const rawLine of value.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }
    const separatorIndex = line.indexOf("=");
    if (separatorIndex <= 0 || separatorIndex === line.length - 1) {
      throw new Error(
        `La variante “${line}” debe usar el formato Atributo=Valor.`,
      );
    }
    const key = line.slice(0, separatorIndex).trim();
    const variantValue = line.slice(separatorIndex + 1).trim();
    if (Object.keys(variant).some((current) => current.toLowerCase() === key.toLowerCase())) {
      throw new Error(`La variante contiene el atributo repetido “${key}”.`);
    }
    variant[key] = variantValue;
  }
  return variant;
}

function formatVariant(variant: Record<string, string>): string {
  return Object.entries(variant)
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
}

function actionErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.isStaleRevision) {
    return "El producto cambió en otra operación. Se actualizará la lista para que vuelvas a intentarlo.";
  }
  return error instanceof Error ? error.message : "La operación no pudo completarse.";
}

export function ProductsView({
  client,
  onNotify,
  refreshNonce,
}: {
  client: ApiClient;
  onNotify: (message: string, tone: "success" | "error") => void;
  refreshNonce: number;
}) {
  const [products, setProducts] = useState<ProductRead[]>([]);
  const [stores, setStores] = useState<StoreRead[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [storeSlug, setStoreSlug] = useState("");
  const [filter, setFilter] = useState<ProductFilter>("all");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] =
    useState<ProductFormState>(emptyProductForm);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<ProductRead | null>(null);
  const [editForm, setEditForm] = useState<ProductFormState>(emptyProductForm);
  const [observationsFor, setObservationsFor] = useState<ProductRead | null>(null);
  const [observations, setObservations] = useState<ObservationRead[]>([]);
  const [observationsLoading, setObservationsLoading] = useState(false);

  const loadProducts = useCallback(
    async (cursor?: string) => {
      const append = Boolean(cursor);
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      setError("");
      try {
        const response = await client.listProducts({
          cursor,
          limit: 50,
          search: search || undefined,
          store_slug: storeSlug || undefined,
          archived: filter === "archived",
          active:
            filter === "active"
              ? true
              : filter === "inactive"
                ? false
                : undefined,
        });
        setProducts((current) =>
          append ? [...current, ...response.data.items] : response.data.items,
        );
        setNextCursor(response.data.next_cursor);
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "No se pudo consultar el catálogo.",
        );
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [client, filter, search, storeSlug],
  );

  useEffect(() => {
    void client
      .listStores()
      .then((response) => setStores(response.data))
      .catch(() => setStores([]));
  }, [client]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadProducts();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadProducts, refreshNonce]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearch(searchDraft.trim());
  }

  async function createProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      const payload: ProductCreate = {
        url: createForm.url.trim(),
        label: createForm.label.trim(),
        expected_brand: createForm.expectedBrand.trim() || null,
        expected_model: createForm.expectedModel.trim() || null,
        expected_variant: parseVariantText(createForm.expectedVariantText),
        expected_is_accessory: createForm.expectedIsAccessory,
        check_interval_minutes: Number(createForm.checkIntervalMinutes),
        active: createForm.active,
      };
      await client.createProduct(payload);
      setCreateOpen(false);
      setCreateForm(emptyProductForm);
      onNotify("Producto registrado correctamente.", "success");
      await loadProducts();
    } catch (createError) {
      onNotify(actionErrorMessage(createError), "error");
    } finally {
      setSaving(false);
    }
  }

  function openEdit(product: ProductRead) {
    setEditing(product);
    setEditForm({
      active: product.active,
      checkIntervalMinutes: String(product.check_interval_minutes),
      expectedBrand: product.expected_brand ?? "",
      expectedIsAccessory: product.expected_is_accessory,
      expectedModel: product.expected_model ?? "",
      expectedVariantText: formatVariant(product.expected_variant),
      label: product.label,
      url: product.source_url,
    });
  }

  async function updateProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing) {
      return;
    }
    setSaving(true);
    try {
      const latest = await client.getProduct(editing.id);
      const payload: ProductPatch = {
        label: editForm.label.trim(),
        expected_brand: editForm.expectedBrand.trim() || null,
        expected_model: editForm.expectedModel.trim() || null,
        expected_is_accessory: editForm.expectedIsAccessory,
        check_interval_minutes: Number(editForm.checkIntervalMinutes),
      };
      const updated = await client.updateProduct(editing.id, payload, {
        etag: latest.meta.etag ?? etagForVersion(latest.data.version),
      });
      const expectedVariant = parseVariantText(editForm.expectedVariantText);
      if (
        JSON.stringify(expectedVariant) !==
        JSON.stringify(latest.data.expected_variant)
      ) {
        if (Object.keys(expectedVariant).length) {
          await client.setProductVariant(
            editing.id,
            { expected_variant: expectedVariant },
            {
              etag: updated.meta.etag ?? etagForVersion(updated.data.version),
            },
          );
        } else {
          await client.clearProductVariant(editing.id, {
            etag: updated.meta.etag ?? etagForVersion(updated.data.version),
          });
        }
      }
      setEditing(null);
      onNotify("Producto actualizado.", "success");
      await loadProducts();
    } catch (updateError) {
      onNotify(actionErrorMessage(updateError), "error");
      if (updateError instanceof ApiError && updateError.isStaleRevision) {
        await loadProducts();
      }
    } finally {
      setSaving(false);
    }
  }

  async function toggleProduct(product: ProductRead) {
    try {
      const latest = await client.getProduct(product.id);
      await client.setProductActivation(
        product.id,
        { active: !latest.data.active },
        { etag: latest.meta.etag ?? etagForVersion(latest.data.version) },
      );
      onNotify(
        latest.data.active ? "Producto desactivado." : "Producto activado.",
        "success",
      );
      await loadProducts();
    } catch (toggleError) {
      onNotify(actionErrorMessage(toggleError), "error");
      await loadProducts();
    }
  }

  async function archiveProduct(product: ProductRead) {
    const confirmed = window.confirm(
      `¿Archivar “${product.label}”? El historial se conservará, pero la API actual no permite restaurarlo.`,
    );
    if (!confirmed) {
      return;
    }
    try {
      const latest = await client.getProduct(product.id);
      await client.archiveProduct(product.id, {
        etag: latest.meta.etag ?? etagForVersion(latest.data.version),
      });
      onNotify("Producto archivado.", "success");
      await loadProducts();
    } catch (archiveError) {
      onNotify(actionErrorMessage(archiveError), "error");
      await loadProducts();
    }
  }

  async function openObservations(product: ProductRead) {
    setObservationsFor(product);
    setObservations([]);
    setObservationsLoading(true);
    try {
      const response = await client.listProductObservations(product.id, {
        limit: 50,
      });
      setObservations(response.data.items);
    } catch (observationError) {
      onNotify(actionErrorMessage(observationError), "error");
    } finally {
      setObservationsLoading(false);
    }
  }

  return (
    <div className="view-stack">
      <section className="view-heading view-heading--actions">
        <div>
          <p className="section-kicker">Catálogo controlado</p>
          <h2>Productos y URLs públicas</h2>
          <p>
            Cada URL se asigna automáticamente al adapter de su dominio. Las
            tiendas nuevas todavía requieren implementación y pruebas.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <PlusIcon />
          Registrar producto
        </Button>
      </section>

      <section className="surface">
        <div className="catalog-toolbar">
          <form className="search-field" onSubmit={submitSearch}>
            <SearchIcon />
            <input
              onChange={(event) => setSearchDraft(event.target.value)}
              placeholder="Buscar por etiqueta, marca o modelo"
              value={searchDraft}
            />
            <button type="submit">Buscar</button>
          </form>
          <label>
            <span className="sr-only">Filtrar por tienda</span>
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
          <label>
            <span className="sr-only">Filtrar por estado</span>
            <select
              onChange={(event) =>
                setFilter(event.target.value as ProductFilter)
              }
              value={filter}
            >
              <option value="all">No archivados</option>
              <option value="active">Activos</option>
              <option value="inactive">Inactivos</option>
              <option value="archived">Archivados</option>
            </select>
          </label>
        </div>

        {loading ? (
          <LoadingBlock label="Consultando el catálogo" />
        ) : error && products.length === 0 ? (
          <EmptyState
            action={<Button onClick={() => void loadProducts()}>Reintentar</Button>}
            description={error}
            title="No se pudo cargar el catálogo"
          />
        ) : products.length === 0 ? (
          <EmptyState
            action={
              filter !== "archived" ? (
                <Button onClick={() => setCreateOpen(true)}>
                  Registrar primer producto
                </Button>
              ) : undefined
            }
            description="No hay productos que coincidan con la búsqueda y los filtros."
            title="Catálogo sin resultados"
          />
        ) : (
          <>
            {error ? <div className="inline-error">{error}</div> : null}
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Producto</th>
                    <th>Tienda</th>
                    <th>Intervalo</th>
                    <th>Última revisión</th>
                    <th>Estado</th>
                    <th><span className="sr-only">Acciones</span></th>
                  </tr>
                </thead>
                <tbody>
                  {products.map((product) => (
                    <tr key={product.id}>
                      <td>
                        <div className="table-product">
                          <strong>{product.label}</strong>
                          <span>
                            {[product.expected_brand, product.expected_model]
                              .filter(Boolean)
                              .join(" · ") || "Sin marca/modelo esperado"}
                          </span>
                        </div>
                      </td>
                      <td>{titleCase(product.store_slug)}</td>
                      <td>{product.check_interval_minutes} min</td>
                      <td>
                        <span title={formatDateTime(product.last_checked_at)}>
                          {formatRelativeTime(product.last_checked_at)}
                        </span>
                      </td>
                      <td>
                        <StatusPill
                          tone={
                            product.archived_at
                              ? "neutral"
                              : product.active
                                ? "success"
                                : "warning"
                          }
                        >
                          {product.archived_at
                            ? "Archivado"
                            : product.active
                              ? "Activo"
                              : "Inactivo"}
                        </StatusPill>
                      </td>
                      <td>
                        <details className="row-menu">
                          <summary aria-label={`Acciones para ${product.label}`}>
                            •••
                          </summary>
                          <div>
                            <button
                              onClick={() => void openObservations(product)}
                              type="button"
                            >
                              Ver historial
                            </button>
                            <a
                              href={product.source_url}
                              rel="noopener noreferrer"
                              target="_blank"
                            >
                              Abrir tienda <ExternalLinkIcon />
                            </a>
                            {!product.archived_at ? (
                              <>
                                <button onClick={() => openEdit(product)} type="button">
                                  Editar
                                </button>
                                <button
                                  onClick={() => void toggleProduct(product)}
                                  type="button"
                                >
                                  {product.active ? "Desactivar" : "Activar"}
                                </button>
                                <button
                                  className="danger-text"
                                  onClick={() => void archiveProduct(product)}
                                  type="button"
                                >
                                  Archivar
                                </button>
                              </>
                            ) : null}
                          </div>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {nextCursor ? (
              <div className="load-more">
                <Button
                  disabled={loadingMore}
                  onClick={() => void loadProducts(nextCursor)}
                  tone="secondary"
                >
                  {loadingMore ? "Cargando…" : "Cargar más"}
                </Button>
              </div>
            ) : null}
          </>
        )}
      </section>

      <Modal
        description="La tienda se detectará desde el dominio. Solo se aceptan adapters habilitados."
        onClose={() => setCreateOpen(false)}
        open={createOpen}
        title="Registrar producto"
      >
        <ProductForm
          form={createForm}
          onChange={setCreateForm}
          onSubmit={createProduct}
          saving={saving}
          submitLabel="Registrar producto"
          stores={stores}
        />
      </Modal>

      <Modal
        description="La URL y la tienda no se modifican. Los cambios usan la versión más reciente del producto."
        onClose={() => setEditing(null)}
        open={Boolean(editing)}
        title="Editar producto"
      >
        <ProductForm
          editing
          form={editForm}
          onChange={setEditForm}
          onSubmit={updateProduct}
          saving={saving}
          submitLabel="Guardar cambios"
          stores={stores}
        />
      </Modal>

      <Modal
        description={observationsFor?.label}
        onClose={() => setObservationsFor(null)}
        open={Boolean(observationsFor)}
        title="Historial de precios"
      >
        {observationsLoading ? (
          <LoadingBlock />
        ) : observations.length ? (
          <div className="observation-list">
            {observations.map((observation) => (
              <article key={observation.id}>
                <div>
                  <strong>
                    {formatCurrency(observation.price, observation.currency)}
                  </strong>
                  <span>{formatDateTime(observation.observed_at)}</span>
                </div>
                <div>
                  <span>{titleCase(observation.availability)}</span>
                  {observation.list_price ? (
                    <small>
                      Lista:{" "}
                      {formatCurrency(
                        observation.list_price,
                        observation.currency,
                      )}
                    </small>
                  ) : null}
                </div>
                <div>
                  <span>{observation.seller_name || "Vendedor no indicado"}</span>
                  {observation.quality_flags.length ? (
                    <small>{observation.quality_flags.join(", ")}</small>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            description="El producto todavía no tiene observaciones guardadas."
            title="Sin historial"
          />
        )}
      </Modal>
    </div>
  );
}

function ProductForm({
  editing = false,
  form,
  onChange,
  onSubmit,
  saving,
  submitLabel,
  stores,
}: {
  editing?: boolean;
  form: ProductFormState;
  onChange: (form: ProductFormState) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  saving: boolean;
  submitLabel: string;
  stores: StoreRead[];
}) {
  const selectedStore = stores.find((store) =>
    store.hosts.some((host) => form.url.includes(host)),
  );
  const minimumInterval = selectedStore?.minimum_interval_minutes ?? 30;

  return (
    <form className="form-grid" onSubmit={onSubmit}>
      <label className="field field--wide">
        <span>URL pública del producto</span>
        <input
          disabled={editing}
          onChange={(event) => onChange({ ...form, url: event.target.value })}
          placeholder="https://tienda.pe/producto"
          required
          type="url"
          value={form.url}
        />
        {selectedStore ? (
          <small>
            Adapter detectado: {selectedStore.display_name}. Intervalo mínimo:{" "}
            {selectedStore.minimum_interval_minutes} minutos.
          </small>
        ) : (
          <small>La API validará si el dominio tiene un adapter habilitado.</small>
        )}
      </label>
      <label className="field field--wide">
        <span>Nombre para identificarlo</span>
        <input
          maxLength={500}
          onChange={(event) => onChange({ ...form, label: event.target.value })}
          required
          value={form.label}
        />
      </label>
      <label className="field">
        <span>Marca esperada</span>
        <input
          onChange={(event) =>
            onChange({ ...form, expectedBrand: event.target.value })
          }
          value={form.expectedBrand}
        />
      </label>
      <label className="field">
        <span>Modelo esperado</span>
        <input
          onChange={(event) =>
            onChange({ ...form, expectedModel: event.target.value })
          }
          value={form.expectedModel}
        />
      </label>
      <label className="field field--wide">
        <span>Variante esperada</span>
        <textarea
          maxLength={2_000}
          onChange={(event) =>
            onChange({ ...form, expectedVariantText: event.target.value })
          }
          placeholder={"Color=Negro\nCapacidad=256 GB"}
          rows={3}
          value={form.expectedVariantText}
        />
        <small>
          Un atributo por línea con el formato Atributo=Valor. Déjalo vacío si
          no necesitas fijar una variante.
        </small>
      </label>
      <label className="field">
        <span>Intervalo de consulta (minutos)</span>
        <input
          min={minimumInterval}
          onChange={(event) =>
            onChange({ ...form, checkIntervalMinutes: event.target.value })
          }
          required
          type="number"
          value={form.checkIntervalMinutes}
        />
      </label>
      <div className="field field--checks">
        <label className="checkbox-field">
          <input
            checked={form.expectedIsAccessory}
            onChange={(event) =>
              onChange({
                ...form,
                expectedIsAccessory: event.target.checked,
              })
            }
            type="checkbox"
          />
          Este producto es un accesorio
        </label>
        {!editing ? (
          <label className="checkbox-field">
            <input
              checked={form.active}
              onChange={(event) =>
                onChange({ ...form, active: event.target.checked })
              }
              type="checkbox"
            />
            Empezar a monitorearlo
          </label>
        ) : null}
      </div>
      <div className="form-actions field--wide">
        <Button disabled={saving} type="submit">
          {saving ? "Guardando…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
