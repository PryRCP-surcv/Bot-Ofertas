"use client";

import { FormEvent, useState } from "react";

import { ApiClient, ApiError } from "@/lib/api";

import { AlertIcon, CheckIcon } from "./icons";
import { Button } from "./ui";

export interface ConnectedApi {
  apiUrl: string;
  client: ApiClient;
}

function connectionErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.isUnauthorized) {
    return "El token no fue aceptado. Copia BOT_API_ADMIN_TOKEN exactamente como está en tu archivo .env.";
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "No se pudo conectar con la API.";
}

export function ConnectionGate({
  onConnected,
}: {
  onConnected: (connection: ConnectedApi) => void;
}) {
  const [apiUrl, setApiUrl] = useState("http://127.0.0.1:8000");
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [connecting, setConnecting] = useState(false);

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setConnecting(true);

    try {
      const client = new ApiClient({ baseUrl: apiUrl, token });
      const health = await client.healthReady();
      if (health.data.status !== "ready") {
        throw new Error("La API respondió, pero todavía no está lista.");
      }
      await client.listStores();
      onConnected({ apiUrl: client.baseUrl, client });
    } catch (connectionError) {
      setError(connectionErrorMessage(connectionError));
    } finally {
      setConnecting(false);
    }
  }

  return (
    <main className="connection-screen">
      <section className="connection-story" aria-labelledby="connection-title">
        <div className="connection-story__brand">
          <span className="brand-mark">B</span>
          <div>
            <strong>Bot Ofertas</strong>
            <span>Monitor de precios públicos</span>
          </div>
        </div>
        <div className="connection-story__copy">
          <p className="section-kicker">Panel administrativo local</p>
          <h1 id="connection-title">
            Controla tu radar de ofertas desde un solo lugar.
          </h1>
          <p>
            Revisa precios, administra productos, solicita rastreos y ajusta la
            detección sin editar código.
          </p>
          <ul className="connection-benefits">
            <li>
              <CheckIcon /> El bot consulta precios públicos, nunca compra.
            </li>
            <li>
              <CheckIcon /> Los límites y pausas de cada tienda siguen activos.
            </li>
            <li>
              <CheckIcon /> Tu credencial permanece únicamente en esta pestaña.
            </li>
          </ul>
        </div>
        <p className="connection-story__foot">
          Diseñado para operar primero en Perú y trabajar con precios en PEN.
        </p>
      </section>

      <section className="connection-card">
        <div>
          <p className="section-kicker">Conexión local</p>
          <h2>Entra al centro de oportunidades</h2>
          <p className="form-intro">
            Mantén la API y el monitor ejecutándose en Ubuntu. El panel se
            conectará directamente a la API local.
          </p>
        </div>

        <form className="form-stack" onSubmit={connect}>
          <label className="field">
            <span>Dirección de la API</span>
            <input
              autoComplete="url"
              onChange={(event) => setApiUrl(event.target.value)}
              placeholder="http://127.0.0.1:8000"
              required
              spellCheck={false}
              type="url"
              value={apiUrl}
            />
            <small>La configuración predeterminada solo escucha en tu PC.</small>
          </label>

          <label className="field">
            <span>Token administrativo</span>
            <input
              autoComplete="off"
              onChange={(event) => setToken(event.target.value)}
              placeholder="Pega BOT_API_ADMIN_TOKEN"
              required
              spellCheck={false}
              type="password"
              value={token}
            />
            <small>No es el token de Telegram y no se guardará en el navegador.</small>
          </label>

          {error ? (
            <div className="form-error" role="alert">
              <AlertIcon />
              <span>{error}</span>
            </div>
          ) : null}

          <Button disabled={connecting} type="submit">
            {connecting ? "Comprobando conexión…" : "Conectar con la API"}
          </Button>
        </form>

        <div className="security-note">
          <span aria-hidden="true">●</span>
          <p>
            <strong>Sesión sin persistencia.</strong> Al recargar o cerrar la
            pestaña tendrás que volver a introducir el token.
          </p>
        </div>
      </section>
    </main>
  );
}
