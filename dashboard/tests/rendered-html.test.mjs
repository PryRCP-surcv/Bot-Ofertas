import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const dashboardRoot = new URL("../", import.meta.url);

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("renderiza la entrada segura del panel administrativo", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html[^>]*lang="es"/i);
  assert.match(html, /<title>Panel administrativo · Bot Ofertas<\/title>/i);
  assert.match(html, /Controla tu radar de ofertas desde un solo lugar\./);
  assert.match(html, /Conectar con la API/);
  assert.match(html, /type="password"/);
  assert.match(html, /http:\/\/127\.0\.0\.1:8000/);
  assert.doesNotMatch(html, /Your site is taking shape|Building your site/i);
  assert.doesNotMatch(html, /BOT_API_ADMIN_TOKEN=/);
});

test("mantiene la credencial solo en memoria y separa las pantallas", async () => {
  const [
    apiClient,
    connectionGate,
    application,
    summary,
    offers,
    products,
    stores,
    subscribers,
    crawls,
    settings,
  ] = await Promise.all([
    readFile(new URL("lib/api.ts", dashboardRoot), "utf8"),
    readFile(new URL("app/components/connection-gate.tsx", dashboardRoot), "utf8"),
    readFile(new URL("app/BotOfertasAdmin.tsx", dashboardRoot), "utf8"),
    readFile(new URL("app/views/summary-view.tsx", dashboardRoot), "utf8"),
    readFile(new URL("app/views/offers-view.tsx", dashboardRoot), "utf8"),
    readFile(new URL("app/views/products-view.tsx", dashboardRoot), "utf8"),
    readFile(new URL("app/views/stores-view.tsx", dashboardRoot), "utf8"),
    readFile(new URL("app/views/subscribers-view.tsx", dashboardRoot), "utf8"),
    readFile(new URL("app/views/crawls-view.tsx", dashboardRoot), "utf8"),
    readFile(new URL("app/views/settings-view.tsx", dashboardRoot), "utf8"),
  ]);

  assert.match(apiClient, /private token: string/);
  assert.match(apiClient, /Authorization/);
  assert.match(apiClient, /getOperationsStatus/);
  assert.match(apiClient, /\/api\/v1\/operations\/status/);
  const executableSource = `${apiClient}\n${connectionGate}\n${application}`
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
  assert.doesNotMatch(
    executableSource,
    /localStorage|sessionStorage|document\.cookie/i,
  );
  assert.match(connectionGate, /type="password"/);
  assert.match(application, /setUnauthorizedHandler/);
  assert.match(application, /loadOperationsStatus/);
  assert.match(application, /15_000/);

  assert.match(summary, /listOffers/);
  assert.match(summary, /Trabajador de rastreo/);
  assert.match(summary, /Última señal/);
  assert.match(summary, /Último ciclo/);
  assert.match(summary, /Ir a rastreo/);
  assert.doesNotMatch(summary, />\s*Rastrear productos\s*</);
  assert.match(offers, /state/);
  assert.match(products, /If-Match|etagForVersion/);
  assert.match(stores, /Añadir una tienda nueva requiere/);
  assert.match(subscribers, /Registrar pago/);
  assert.match(subscribers, /makeIdempotencyKey\("beta-payment"\)/);
  assert.match(subscribers, /no expulsa miembros por sí solo/i);
  assert.doesNotMatch(subscribers, /número de tarjeta|card_number/i);
  assert.match(crawls, /Idempotency|makeIdempotencyKey/);
  assert.match(crawls, /Elegibles visibles/);
  assert.match(crawls, /Todos los elegibles activos/);
  assert.match(crawls, /Revisar envío/);
  assert.match(crawls, /Confirmar y enviar a la cola/);
  assert.match(crawls, /productIsDue/);
  assert.match(settings, /changeReason/);
});
