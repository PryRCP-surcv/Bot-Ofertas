# Operación de la Fase 4A: API administrativa

La Fase 4A incorpora un plano de control HTTP sobre el monitor existente. La API
permite administrar productos, consultar historial y ofertas, cambiar la política
de detección y solicitar rastreos. No compra, no consulta páginas por sí misma y
no reemplaza al monitor: las solicitudes de rastreo se guardan en PostgreSQL y
`bot-ofertas run` las ejecuta respetando los intervalos, cuotas y pausas de cada
tienda.

## Qué queda disponible

- Autenticación administrativa mediante `Authorization: Bearer`.
- Alta, edición, activación, variante y archivado lógico de productos.
- Consulta paginada de observaciones, ofertas, confirmaciones y corridas.
- Estados de tienda y última ejecución.
- Cola persistente e idempotente para rastreos solicitados manualmente.
- Política de ejecución y detección versionada, auditable y sin secretos.
- Comprobaciones de vida y disponibilidad.
- Documentación OpenAPI local.

El panel visual de la Fase 4B está disponible en `dashboard/`. Swagger UI sigue
siendo útil para revisar y probar el contrato HTTP directamente.

## Primera configuración

Abre Ubuntu y sitúate en el proyecto:

```bash
cd /mnt/c/Users/TU_USUARIO_WINDOWS/Documents/Proyectos/bot-ofertas
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/bot-ofertas"
```

Actualiza el entorno y la base de datos:

```bash
docker compose up -d postgres
uv sync --locked
uv run bot-ofertas db upgrade
```

El `compose.yaml` actual levanta PostgreSQL; la API y el monitor siguen siendo
procesos locales separados.

Genera una credencial administrativa:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copia el resultado una sola vez en el `.env` real:

```dotenv
BOT_API_ADMIN_TOKEN=PEGA_AQUI_EL_VALOR_GENERADO
BOT_API_HOST=127.0.0.1
BOT_API_PORT=8000
BOT_API_CORS_ORIGINS=http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:5173,http://localhost:5173
BOT_API_DOCS_ENABLED=true
```

No uses el token de Telegram como token administrativo. Tampoco guardes el
token administrativo en `.env.example`, Git, capturas, mensajes o código del
futuro panel. La API rechaza valores cortos y el marcador `CHANGE_ME`.
Al cambiar el token debes reiniciar la API; esta etapa admite una sola
credencial y no mantiene una ventana con la clave anterior.

## Iniciar el sistema

Se necesitan dos terminales de Ubuntu.

Terminal 1, monitor y trabajador de la cola:

```bash
cd /mnt/c/Users/TU_USUARIO_WINDOWS/Documents/Proyectos/bot-ofertas
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/bot-ofertas"
uv run bot-ofertas run
```

Terminal 2, API:

```bash
cd /mnt/c/Users/TU_USUARIO_WINDOWS/Documents/Proyectos/bot-ofertas
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/bot-ofertas"
uv run bot-ofertas-api
```

Después abre:

- Swagger UI: `http://127.0.0.1:8000/docs`
- Estado del proceso: `http://127.0.0.1:8000/health/live`
- Estado de dependencias: `http://127.0.0.1:8000/health/ready`
- Panel local de Fase 4B: `http://localhost:3000` después de ejecutar
  `npm run dev` dentro de `dashboard/`

En Swagger pulsa **Authorize** e introduce el valor de
`BOT_API_ADMIN_TOKEN`. Los dos endpoints de salud son públicos; todos los
endpoints bajo `/api/v1` requieren la credencial.

Si el monitor está apagado, se pueden registrar productos y encolar trabajos,
pero estos permanecerán en estado `queued`. Al volver a iniciar
`bot-ofertas run`, el monitor los recoge.

## Recursos principales

| Método y ruta | Función |
| --- | --- |
| `GET /api/v1/stores` | Tiendas, productos, pausa y última corrida |
| `GET/POST /api/v1/products` | Lista o registra productos |
| `GET/PATCH/DELETE /api/v1/products/{id}` | Consulta, edita o archiva |
| `PUT /api/v1/products/{id}/activation` | Activa o desactiva |
| `PUT/DELETE /api/v1/products/{id}/variant` | Fija o limpia la variante esperada |
| `GET /api/v1/products/{id}/observations` | Historial de precios |
| `GET /api/v1/offers` | Ofertas activas, pendientes o históricas |
| `GET /api/v1/confirmations` | Candidatas pendientes de segunda observación |
| `GET /api/v1/crawl-runs` | Auditoría de ejecuciones Scrapy |
| `POST/GET /api/v1/crawl-jobs` | Solicita o consulta rastreos |
| `POST /api/v1/crawl-jobs/{id}/cancel` | Cancela un trabajo abierto |
| `GET/PATCH /api/v1/settings` | Consulta o cambia la política versionada |

Las listas grandes usan `limit` y `cursor`; no se debe modificar ni construir
manualmente el cursor devuelto como `next_cursor`.

### Productos

La tienda se obtiene del dominio de la URL usando `StoreRegistry`. No existe un
endpoint para crear una tienda arbitraria: cada tienda debe seguir teniendo un
adapter revisado, límites propios y pruebas.

Las respuestas de producto incluyen un encabezado `ETag`, por ejemplo `"3"`.
Toda modificación exige enviar esa versión:

```http
If-Match: "3"
```

Si otra operación ya cambió el producto, la API devuelve `412` y el cliente debe
volver a leerlo. `DELETE` realiza archivado lógico: conserva el historial, pero
el scheduler deja de rastrear el producto.

### Ofertas

`GET /api/v1/offers` devuelve por defecto `state=active`: solo la decisión más
reciente de la política vigente, confirmada, disponible, no archivada y observada
durante las últimas 24 horas.

También se admiten:

- `state=awaiting`: candidatas que esperan confirmación.
- `state=history`: decisiones históricas para auditoría.

Se puede filtrar por tienda, clasificación y estado de notificación. Cada
resultado conserva la versión del detector, la huella de política, señales,
confianza y razones.

### Solicitar un rastreo

`POST /api/v1/crawl-jobs` admite de 1 a 20 identificadores explícitos y exige:

```http
Idempotency-Key: una-clave-unica-por-accion
```

Repetir exactamente la petición con la misma clave devuelve el mismo trabajo.
Reutilizar la clave con otro contenido devuelve `409`. La solicitud no fuerza
consultas anticipadas: el trabajador sigue respetando el intervalo del producto,
la cuota de la tienda, `robots.txt`, backoff, CAPTCHA y circuitos de seguridad.
El total puede distribuirse entre tiendas, pero cada trabajo también debe
respetar el máximo propio de cada adapter; por ejemplo, Oechsle y Promart admiten
cinco productos cada una.

Los estados del trabajo son:

- `queued`: espera trabajador.
- `running`: tiene un lease temporal.
- `retrying`: puede recuperarse tras un fallo o lease vencido.
- `succeeded`, `partial`, `failed` o `cancelled`: estados terminales.

El trabajo y cada producto conservan por separado el resultado y la corrida que
lo atendió. El monitor procesa como máximo un trabajo administrativo por ciclo y
mantiene su lease con heartbeats durante Scrapy. Cuando hay uno, ocupa la etapa
de rastreo de ese ciclo y los productos ordinarios pendientes continúan en el
siguiente. Si un producto todavía no está vencido, está leased o su tienda está
pausada, queda `skipped` y el trabajo termina como `partial`, no como éxito
completo.

La cancelación de un trabajo en `queued` es inmediata. Si Scrapy ya está
ejecutándose, la cancelación es cooperativa: el estado final será `cancelled`,
pero las solicitudes públicas que ya salieron pueden terminar y conservar una
observación válida.

### Cambiar la política

`GET /api/v1/settings` devuelve la configuración efectiva y su `ETag`. El token
de Telegram nunca se devuelve; solo aparecen indicadores booleanos de si está
configurado.

Para modificar un valor, envía el `ETag` actual:

```http
PATCH /api/v1/settings
If-Match: "4"
Idempotency-Key: cambio-umbral-2026-07-28
X-Change-Reason: Ajuste revisado de confianza
Content-Type: application/json

{"minimum_alert_confidence": 60}
```

Cada cambio crea una revisión inmutable en `admin_config_revisions`. Las
decisiones nuevas guardan tanto la revisión como una huella de la política.
Cambiar la configuración no vuelve a notificar automáticamente todo el historial.
El monitor vuelve a resolver la política para los ciclos siguientes. El intervalo
base `scheduler_poll_seconds`, en cambio, controla al proceso padre y requiere
reiniciar `bot-ofertas run` para aplicarse.

## Seguridad y red

La configuración predeterminada escucha únicamente en `127.0.0.1`. No cambies
el host a `0.0.0.0` ni expongas el puerto a Internet sin añadir antes HTTPS,
gestión de usuarios, rotación de credenciales y una capa de acceso adecuada.

`BOT_API_CORS_ORIGINS` acepta una lista de orígenes exactos separados por comas.
No usa comodines. Los valores predeterminados permiten el panel local de la Fase
4B en `http://127.0.0.1:3000` y `http://localhost:3000`; también conservan el
puerto `5173` para clientes locales compatibles. La credencial se pide al
usuario y se mantiene en memoria: no se compila dentro del frontend ni se guarda
en una variable `VITE_*`. CORS protege al navegador frente a orígenes no
autorizados, pero no autentica y no bloquea clientes como `curl`.

`BOT_API_DOCS_ENABLED=false` oculta Swagger, ReDoc y OpenAPI; no desactiva ni
protege los endpoints.

Los errores generados por los endpoints tienen formato Problem Details e incluyen
`request_id`. Ese identificador sirve para correlacionar una respuesta con los
logs sin revelar credenciales ni errores internos.

## Diagnóstico

Si `/health/ready` devuelve `503`, comprueba:

```bash
docker compose ps
uv run alembic current
uv run bot-ofertas store list
```

La API requiere que PostgreSQL esté disponible, que Alembic esté en
`0009_phase4_admin` y que los adapters habilitados carguen sin errores.

No ejecutes `alembic downgrade 0008_conditioned_offers` sin una copia de
seguridad: el downgrade elimina la cola y las revisiones administrativas, y debe
reducir decisiones repetidas bajo políticas distintas para volver al esquema
anterior.

Si un trabajo permanece en `queued`, confirma que `uv run bot-ofertas run` siga
activo. La API y el monitor son procesos distintos que coordinan mediante
PostgreSQL.

## Pruebas

```bash
uv run ruff check .
uv run pytest tests/unit -q -p no:cacheprovider
RUN_POSTGRES_TESTS=1 uv run pytest tests/integration -q -p no:cacheprovider
uv run alembic check
```

Las pruebas cubren autenticación uniforme, CORS, errores, cursores, ETag,
idempotencia, revisiones de configuración, leases, cancelación, modelos y el
flujo transaccional de la API contra PostgreSQL.
