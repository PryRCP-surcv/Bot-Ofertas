"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminShell, type AdminView } from "./components/admin-shell";
import {
  ConnectionGate,
  type ConnectedApi,
} from "./components/connection-gate";
import { Toast } from "./components/ui";
import { CrawlsView } from "./views/crawls-view";
import { OffersView } from "./views/offers-view";
import { ProductsView } from "./views/products-view";
import { SettingsView } from "./views/settings-view";
import { StoresView } from "./views/stores-view";
import { SummaryView } from "./views/summary-view";

interface ToastState {
  id: number;
  message: string;
  tone: "success" | "error";
}

export function BotOfertasAdmin() {
  const [connection, setConnection] = useState<ConnectedApi | null>(null);

  const disconnect = useCallback(() => {
    setConnection((current) => {
      current?.client.clearToken();
      current?.client.setUnauthorizedHandler(undefined);
      return null;
    });
  }, []);

  if (!connection) {
    return <ConnectionGate onConnected={setConnection} />;
  }

  return <AdminWorkspace connection={connection} onDisconnect={disconnect} />;
}

function AdminWorkspace({
  connection,
  onDisconnect,
}: {
  connection: ConnectedApi;
  onDisconnect: () => void;
}) {
  const [view, setView] = useState<AdminView>("summary");
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  useEffect(() => {
    connection.client.setUnauthorizedHandler(onDisconnect);
    return () => connection.client.setUnauthorizedHandler(undefined);
  }, [connection.client, onDisconnect]);

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(() => setToast(null), 5_000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  function notify(message: string, tone: "success" | "error") {
    setToast({ id: Date.now(), message, tone });
  }

  function refresh() {
    setRefreshing(true);
    setRefreshNonce((current) => current + 1);
    window.setTimeout(() => setRefreshing(false), 750);
  }

  return (
    <>
      <AdminShell
        apiUrl={connection.apiUrl}
        loading={refreshing}
        onDisconnect={onDisconnect}
        onRefresh={refresh}
        onViewChange={setView}
        view={view}
      >
        {view === "summary" ? (
          <SummaryView
            client={connection.client}
            onNavigate={setView}
            refreshNonce={refreshNonce}
          />
        ) : null}
        {view === "offers" ? (
          <OffersView client={connection.client} refreshNonce={refreshNonce} />
        ) : null}
        {view === "products" ? (
          <ProductsView
            client={connection.client}
            onNotify={notify}
            refreshNonce={refreshNonce}
          />
        ) : null}
        {view === "stores" ? (
          <StoresView client={connection.client} refreshNonce={refreshNonce} />
        ) : null}
        {view === "crawls" ? (
          <CrawlsView
            client={connection.client}
            onNotify={notify}
            refreshNonce={refreshNonce}
          />
        ) : null}
        {view === "settings" ? (
          <SettingsView
            client={connection.client}
            onNotify={notify}
            refreshNonce={refreshNonce}
          />
        ) : null}
      </AdminShell>
      {toast ? (
        <Toast
          key={toast.id}
          message={toast.message}
          onDismiss={() => setToast(null)}
          tone={toast.tone}
        />
      ) : null}
    </>
  );
}
