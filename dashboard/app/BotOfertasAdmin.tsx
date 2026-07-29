"use client";

import { useCallback, useEffect, useState } from "react";

import type { OperationsStatusRead } from "@/lib/types";

import { AdminShell, type AdminView } from "./components/admin-shell";
import {
  ConnectionGate,
  type ConnectedApi,
} from "./components/connection-gate";
import { Toast } from "./components/ui";
import { CrawlsView } from "./views/crawls-view";
import { DiscoveryView } from "./views/discovery-view";
import { DistributionView } from "./views/distribution-view";
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
  const [operationsStatus, setOperationsStatus] =
    useState<OperationsStatusRead | null>(null);
  const [operationsError, setOperationsError] = useState("");

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

  const loadOperationsStatus = useCallback(async () => {
    try {
      const response = await connection.client.getOperationsStatus();
      setOperationsStatus(response.data);
      setOperationsError("");
    } catch (statusError) {
      setOperationsError(
        statusError instanceof Error
          ? statusError.message
          : "No se pudo consultar el estado del trabajador.",
      );
    }
  }, [connection.client]);

  useEffect(() => {
    const initialTimer = window.setTimeout(() => {
      void loadOperationsStatus();
    }, 0);
    const pollingTimer = window.setInterval(() => {
      void loadOperationsStatus();
    }, 15_000);
    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(pollingTimer);
    };
  }, [loadOperationsStatus, refreshNonce]);

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
        operationsError={operationsError}
        operationsStatus={operationsStatus}
        view={view}
      >
        {view === "summary" ? (
          <SummaryView
            client={connection.client}
            onNavigate={setView}
            operationsError={operationsError}
            operationsStatus={operationsStatus}
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
        {view === "discovery" ? (
          <DiscoveryView
            client={connection.client}
            onNotify={notify}
            refreshNonce={refreshNonce}
          />
        ) : null}
        {view === "distribution" ? (
          <DistributionView
            client={connection.client}
            onNotify={notify}
            refreshNonce={refreshNonce}
          />
        ) : null}
        {view === "crawls" ? (
          <CrawlsView
            client={connection.client}
            onNotify={notify}
            operationsError={operationsError}
            operationsStatus={operationsStatus}
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
