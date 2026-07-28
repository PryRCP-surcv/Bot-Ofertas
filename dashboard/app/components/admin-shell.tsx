"use client";

import type { ReactNode } from "react";
import { useState } from "react";

import {
  BoxIcon,
  HomeIcon,
  MenuIcon,
  RadarIcon,
  RefreshIcon,
  SettingsIcon,
  StoreIcon,
  TagIcon,
} from "./icons";
import { Button } from "./ui";

export type AdminView =
  | "summary"
  | "offers"
  | "products"
  | "stores"
  | "crawls"
  | "settings";

const navigation: Array<{
  id: AdminView;
  label: string;
  icon: typeof HomeIcon;
}> = [
  { id: "summary", label: "Resumen", icon: HomeIcon },
  { id: "offers", label: "Ofertas", icon: TagIcon },
  { id: "products", label: "Productos", icon: BoxIcon },
  { id: "stores", label: "Tiendas", icon: StoreIcon },
  { id: "crawls", label: "Rastreo", icon: RadarIcon },
  { id: "settings", label: "Configuración", icon: SettingsIcon },
];

const viewTitles: Record<AdminView, { eyebrow: string; title: string }> = {
  summary: { eyebrow: "Centro de oportunidades", title: "Buenos días, Surich" },
  offers: { eyebrow: "Detección y evidencia", title: "Ofertas encontradas" },
  products: { eyebrow: "Catálogo vigilado", title: "Productos monitoreados" },
  stores: { eyebrow: "Adaptadores peruanos", title: "Salud de tiendas" },
  crawls: { eyebrow: "Operación responsable", title: "Rastreos y ejecuciones" },
  settings: { eyebrow: "Política versionada", title: "Configuración del monitor" },
};

export function AdminShell({
  apiUrl,
  children,
  loading,
  onDisconnect,
  onRefresh,
  onViewChange,
  view,
}: {
  apiUrl: string;
  children: ReactNode;
  loading: boolean;
  onDisconnect: () => void;
  onRefresh: () => void;
  onViewChange: (view: AdminView) => void;
  view: AdminView;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const currentTitle = viewTitles[view];

  function selectView(nextView: AdminView) {
    onViewChange(nextView);
    setMenuOpen(false);
  }

  return (
    <div className="admin-shell">
      <aside className={`sidebar ${menuOpen ? "sidebar--open" : ""}`}>
        <div className="sidebar__brand">
          <span className="brand-mark">B</span>
          <div>
            <strong>Bot Ofertas</strong>
            <span>Monitor de precios</span>
          </div>
        </div>

        <p className="sidebar__label">Administración</p>
        <nav className="sidebar__nav" aria-label="Navegación principal">
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <button
                aria-current={view === item.id ? "page" : undefined}
                className={view === item.id ? "active" : ""}
                key={item.id}
                onClick={() => selectView(item.id)}
                type="button"
              >
                <Icon />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="sidebar__connection">
          <div>
            <span className="connection-dot" />
            <strong>API conectada</strong>
          </div>
          <small title={apiUrl}>{apiUrl.replace(/^https?:\/\//, "")}</small>
          <button onClick={onDisconnect} type="button">
            Cerrar sesión
          </button>
        </div>
      </aside>

      {menuOpen ? (
        <button
          aria-label="Cerrar menú"
          className="sidebar-scrim"
          onClick={() => setMenuOpen(false)}
          type="button"
        />
      ) : null}

      <main className="admin-main">
        <header className="admin-topbar">
          <div className="admin-topbar__title">
            <button
              aria-label="Abrir menú"
              className="mobile-menu-button"
              onClick={() => setMenuOpen(true)}
              type="button"
            >
              <MenuIcon />
            </button>
            <div>
              <p className="section-kicker">{currentTitle.eyebrow}</p>
              <h1>{currentTitle.title}</h1>
            </div>
          </div>
          <div className="admin-topbar__actions">
            <span className="monitor-chip">
              <span />
              API lista
            </span>
            <Button
              aria-label="Actualizar datos"
              disabled={loading}
              onClick={onRefresh}
              tone="secondary"
              type="button"
            >
              <RefreshIcon className={loading ? "spin" : ""} />
              <span className="refresh-label">Actualizar</span>
            </Button>
            <span className="avatar" aria-label="Perfil de Surich">
              SU
            </span>
          </div>
        </header>
        <div className="admin-content">{children}</div>
      </main>
    </div>
  );
}
