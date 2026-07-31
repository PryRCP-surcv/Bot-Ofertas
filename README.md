# Bot de ofertas

Monitor responsable de precios públicos para tiendas online de Perú. El objetivo
es conservar historial por SKU, variante y vendedor para detectar
ofertas excepcionales y posibles errores de precio sin realizar compras.

## Estado actual

Las Fases 1, 2, 3, 4A, 4B, 4C, 5.1, 5.2, 6.1 y la ampliación 6.2 están
implementadas para ejecución local y privada:

1. Se registra una URL pública de producto.
2. El registro de tiendas reconoce el dominio, elige el adapter habilitado y
   normaliza la URL. El usuario no escribe manualmente el nombre de la tienda.
3. Scrapy verifica y obedece `robots.txt`.
4. El spider de esa tienda consulta únicamente recursos públicos permitidos.
5. Cada combinación SKU + vendedor se normaliza de forma independiente.
6. Un pipeline común valida el resultado y PostgreSQL conserva la ejecución y
   la observación de precio.
7. El detector `phase3-v2` compara precio anterior, medianas de 7, 30 y 90
   días, mínimo histórico, precio de lista y equivalentes verificados.
8. La severidad y la confianza se calculan por separado, y cada decisión
   conserva sus señales, muestras y motivos.
9. Una primera detección queda esperando confirmación. Solo una observación
   independiente, obtenida en otra ejecución después del intervalo del producto,
   puede confirmarla.
10. Una capa persistente elimina alertas repetidas y aplica reintentos.
11. Telegram recibe las ofertas confirmadas cuando sus credenciales están
    configuradas.
12. Un scheduler local ejecuta el ciclo completo sin solapar corridas.
13. Una API administrativa autenticada permite gestionar productos, consultar
    resultados, versionar la política y encolar rastreos.
14. Un panel web responsive consume esa API para operar productos, ofertas,
    tiendas, rastreos y configuración sin editar código.
15. El trabajador publica un heartbeat persistente y el panel distingue el
    estado de la API del estado real del rastreo.
16. Docker mantiene PostgreSQL, API, worker, watchdog, respaldos y panel en
    segundo plano, con reinicio automático y logs rotados.
17. Scrapy descubre progresivamente fichas desde los sitemaps oficiales de nueve
    tiendas, con rotación, leases, deduplicación y límites diarios.
18. Los candidatos requieren aprobación administrativa antes de convertirse en
    productos monitoreados.
19. El panel muestra la salud de la audiencia beta de Telegram y permite enviar
    una prueba fija, sin revelar el token ni el chat ID.
20. La beta comercial administra suscriptores, vigencias, accesos manuales a
    Telegram, pagos externos confirmados, renovaciones y controles de
    lanzamiento sin almacenar tarjetas ni credenciales bancarias.

La primera prueba de la Fase 1 guardó correctamente una barra de sonido a
`PEN 179.00`, con precio de lista `PEN 499.00`, disponibilidad y vendedor.
La validación viva de la Fase 2 guardó después una observación de Oechsle y otra
de Promart, sin errores.

Coolbox, Oechsle, Promart, Cassinelli, EFE, La Curacao, plazaVea, Topitop y Vega
están habilitadas. Promart, plazaVea y Vega solo alertan con vendedor propio y
unidad fija, y recuerdan confirmar delivery para el distrito de Lima.
Cassinelli reutiliza el núcleo VTEX; EFE y La Curacao usan Product/Offer
JSON-LD contrastado con el precio HTML. Topitop conserva cada talla como SKU y
variante independiente. Cada tienda mantiene política, dominio, vendedor,
límites, fixtures y pruebas propios.

El detector de Fase 3, la confirmación, la deduplicación, Telegram, el scheduler,
la API de Fase 4A, el panel de Fase 4B y la operación local robusta de Fase 4C ya
están implementados. Las equivalencias entre tiendas son grupos creados y
verificados manualmente: deben representar la misma marca, modelo y variante, y
admiten como máximo una publicación por tienda. Aún no existen WhatsApp, Gmail,
autenticación multiusuario, cobro automático, administración automática de
miembros ni despliegue permanente en un servidor.

Telegram es actualmente un canal de salida: envía alertas, pero todavía no
responde `/start`, `/ofertas`, `Hola` ni otros comandos. El panel y la API son
herramientas privadas del administrador; los suscriptores beta reciben las
ofertas mediante Telegram, sin acceso al panel. El monitoreo continúa en segundo
plano mientras la PC y Docker Desktop permanezcan encendidos.

## Dónde está cada cosa

- Código y documentación: la carpeta donde se clonó este repositorio en Windows.
- Imágenes y procesos de Python, API y panel: servicios de Docker Compose.
- PostgreSQL: servicio `postgres` de Docker Compose.
- Datos de PostgreSQL:
  volumen persistente `bot-ofertas_postgres_data`
- Respaldos: `backups/postgres` dentro del proyecto.

Apagar la PC no elimina el proyecto ni el historial, pero sí detiene
temporalmente los rastreos y las alertas. Si Docker Desktop está configurado para
iniciarse con Windows, los servicios con política de reinicio vuelven a
levantarse. De todos modos, conviene comprobar su estado después de reiniciar.

## Volver a ejecutarlo después de reiniciar

1. Abre Docker Desktop y espera a que indique **Engine running**.
2. Abre PowerShell en la raíz del proyecto.
3. Ejecuta:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bot-ofertas.ps1 start
```

El script construye lo necesario, aplica las migraciones y deja activos
`postgres`, `api`, `worker`, `watchdog`, `backup` y `dashboard`. El servicio
`migrations` termina con código `0` después de actualizar el esquema; eso es
normal. El head actual de migraciones es `0015_offer_episode_deduplication`.

Comprueba el estado:

```powershell
.\scripts\bot-ofertas.ps1 status
```

No hace falta conservar PowerShell, Ubuntu ni tres terminales abiertas. Después
abre `http://localhost:3000`, escribe
`http://127.0.0.1:8000` como API y pega el valor real de
`BOT_API_ADMIN_TOKEN`. El token solo permanece en memoria; al recargar la
página se solicita nuevamente. La guía específica está en
[`dashboard/README.md`](dashboard/README.md).

Swagger queda en `http://127.0.0.1:8000/docs`. El estado operativo autenticado,
incluido el heartbeat real del worker y el tamaño de la cola, se consulta en
`GET /api/v1/operations/status`. La operación, reinicio, logs y respaldos están
documentados en [Fase 4C: operación local económica](docs/phase4c-operations.md).

Los puertos del host se toman de `.env`; por ejemplo, se puede usar `5433` para
PostgreSQL si `5432` ya está ocupado.

## Uso avanzado desde un entorno de desarrollo

El panel cubre la operación cotidiana. Los siguientes comandos siguen
disponibles para desarrollo o diagnóstico con el entorno Python instalado; no
son necesarios para mantener los contenedores activos.

Ver las tiendas registradas, sus dominios y si están habilitadas:

```bash
uv run bot-ofertas store list
```

Consultar o ejecutar el descubrimiento acotado:

```bash
uv run bot-ofertas discovery sources
uv run bot-ofertas discovery run
uv run bot-ofertas discovery candidates --status pending
```

Agregar una ficha pública de una tienda habilitada:

```bash
uv run bot-ofertas product add \
  "https://www.coolbox.pe/barra-sonido-decibel-bluetooth-100w-negro-mel-s25/p" \
  --label "Barra de sonido Decibel S25" \
  --brand "Decibel" \
  --model "S25" \
  --variant "Color=Negro" \
  --interval 60
```

La tienda se detecta a partir del dominio de la URL. Si el dominio no está
registrado o está deshabilitado, el comando se detiene sin guardar el producto y
muestra las tiendas compatibles. El registro impide que dos adapters reclamen el
mismo dominio.

Listar productos:

```bash
uv run bot-ofertas product list
```

Ejecutar un ciclo completo:

```bash
uv run bot-ofertas run --once
```

Mantener el monitor activo:

```bash
uv run bot-ofertas run
```

También se pueden ejecutar por separado `crawl`, `analyze` y `notify`. Para ver
resultados:

```bash
uv run bot-ofertas history --limit 20
uv run bot-ofertas alert list --limit 20
uv run bot-ofertas confirmation list --limit 20
```

Existe `crawl --force` para pruebas manuales, pero no debe usarse repetidamente.
El límite por ejecución es 20 URLs y el intervalo mínimo aceptado es 30 minutos.
`crawl --force` no permite confirmar una candidata antes del intervalo configurado
para el producto.

La guía completa de configuración, Telegram, estados, deduplicación y
recuperación está en [Operación de la Fase 1](docs/phase1-operations.md).
La selección de variantes, equivalencias, confianza y segunda comprobación está
en [Operación de la Fase 3](docs/phase3-operations.md). La autenticación,
endpoints, cola y configuración versionada están en
[Operación de la Fase 4A](docs/phase4-api.md). El arranque unificado, watchdog,
logs y respaldos están en
[Fase 4C: operación local económica](docs/phase4c-operations.md).
El descubrimiento, sus límites y la revisión de candidatos están en
[Fase 5.1: descubrimiento controlado](docs/phase5-discovery.md).
La ampliación inicial a seis tiendas y la audiencia beta están en
[Fase 5.2: nuevas tiendas y beta por Telegram](docs/phase5-2-expansion-beta.md).
La administración de suscriptores, pagos externos, renovaciones y lista de
lanzamiento está en
[Fase 6.1: beta comercial controlada](docs/phase6-1-commercial-beta.md).
La cobertura efectiva de Promart y Oechsle, y la incorporación de plazaVea,
Topitop y Vega, están en
[Fase 6.2: cobertura efectiva y nueve tiendas](docs/phase6-2-effective-coverage.md).

Detener todo sin perder el historial:

```powershell
.\scripts\bot-ofertas.ps1 stop
```

## Pruebas

Pruebas offline de dominio, cuotas, variantes, marketplace, agotados, centinelas
y condiciones:

```bash
uv run pytest -q -p no:cacheprovider
```

Incluir la prueba transaccional contra PostgreSQL local:

```bash
RUN_POSTGRES_TESTS=1 uv run pytest -q -p no:cacheprovider
```

Las pruebas de PostgreSQL crean una base temporal aislada, aplican todas las
migraciones y eliminan únicamente esa base al terminar.

Revisión estática:

```bash
uv run ruff check .
```

El workflow de GitHub Actions ejecuta Ruff, pruebas unitarias, migraciones,
integración con PostgreSQL efímero y, para el panel, ESLint, TypeScript, build de
producción, auditoría de dependencias de runtime y pruebas en cada `push` a
`main` y pull request. Telegram permanece desactivado en CI.

## Arquitectura multi-tienda

```text
URL registrada
  -> StoreRegistry: detecta dominio y normaliza URL
  -> tracked_products
  -> API: CRUD con ETag / cola crawl_jobs
  -> claim_due: lease PostgreSQL
  -> adapter/spider correspondiente
  -> normalización por SKU + vendedor
  -> validación PriceObservation
  -> pipeline PostgreSQL común
  -> historial inmutable
  -> DealDetector phase3-v2
  -> evidencia histórica y equivalentes verificados
  -> puntuación de confianza
  -> confirmación en otra ejecución
  -> deduplicación persistente
  -> delivery Telegram con lease y backoff
  -> heartbeat persistente del worker
  -> watchdog: alerta y recuperación deduplicadas
```

El alta progresiva de Fases 5.1 y 5.2 usa un flujo separado antes de
`tracked_products`:

```text
Sitemap oficial revisado
  -> discovery_sources: intervalo, cursor y límites
  -> Scrapy: robots.txt + índice + un product-N.xml
  -> discovery_candidates: URL canónica deduplicada
  -> aprobación administrativa
  -> tracked_products
  -> flujo normal de precio, detección y Telegram
```

`StoreRegistry` reúne adapters integrados en el proyecto y adapters publicados
por plugins mediante el entry point `bot_ofertas.store_adapters`. La CLI obtiene
del registro la tienda correspondiente a una URL; el proceso de crawl agrupa los
productos por tienda y ejecuta el spider declarado por cada adapter. El pipeline
persiste observaciones usando el `store_slug` del spider, sin condicionales
específicos de Coolbox.

Antes de entregar trabajo a Scrapy, PostgreSQL reserva cada producto con un
lease temporal. La selección usa `SELECT ... FOR UPDATE SKIP LOCKED`, por lo que
varios workers pueden reclamar lotes concurrentemente sin procesar la misma fila.
Cada observación vuelve a comprobar y bloquear en PostgreSQL el producto, la
tienda, la URL y el token del lease dentro de la misma transacción que guarda el
historial. Un worker que perdió su lease no puede escribir datos atrasados. Al
terminar, cada producto se completa con su token; si una ejecución se aborta, el
lote se libera, y si un proceso desaparece, el vencimiento permite recuperarlo.

Las cuotas se reclaman por tienda con reparto rotativo, respetando el límite y el
intervalo actual de cada adapter. Los fallos aplican backoff exponencial por
producto. Un HTTP 403, 429, 503 o una señal de CAPTCHA abre además un circuito
persistente de seis horas para toda la tienda, revoca sus leases pendientes y no
se omite ni siquiera con `crawl --force`.

Tablas:

- `tracked_products`: URLs, tienda, frecuencia, estado del lease y fallos
  consecutivos.
- `store_crawl_states`: pausas de seguridad y bloqueos consecutivos por tienda.
- `crawl_runs`: auditoría de cada ejecución, estado y errores.
- `price_observations`: historial inmutable de precio, precio de lista, cuotas,
  variante, vendedor, condición y disponibilidad.
- `equivalent_product_groups` y `equivalent_product_memberships`: equivalencias
  entre publicaciones verificadas manualmente.
- `deal_detections`: decisión versionada, severidad, confianza, señales,
  referencias, confirmación y descartes por observación.
- `offer_confirmation_states`: candidatas que esperan una segunda observación
  independiente.
- `offer_alert_states`: episodio activo e historial de deduplicación por oferta
  exacta. Una oferta continua no vuelve a enviarse solo porque pasen 24 horas.
- `notification_deliveries`: entregas Telegram, leases, intentos y errores
  sanitizados.
- `admin_config_revisions`: revisiones inmutables y auditables de la política
  operativa, sin secretos.
- `crawl_jobs` y `crawl_job_items`: solicitudes manuales idempotentes, leases y
  resultado por producto.
- `worker_runtime_states`: heartbeat, ciclo y estado operativo del worker.
- `worker_watchdog_states`: incidentes y avisos de caída o recuperación sin
  duplicados.
- `beta_subscribers`: vigencia, estado comercial y situación manual del acceso
  a Telegram.
- `beta_payments`: pagos externos confirmados en PEN, cobertura e idempotencia.
- `beta_launch_checklist_items`: controles persistentes previos al lanzamiento.

El precio total y las cuotas son campos distintos: una cuota individual nunca se
usa como precio total. Las condiciones de tarjeta o medio de pago, membresía,
cupón, cantidad mínima y promoción son informativas y aparecen en la CLI y en
Telegram; no bloquean por sí solas. Las dos observaciones que confirman una
oferta deben conservar tanto la misma familia como la misma huella opaca de la
condición exacta publicada. Así, por ejemplo, dos tarjetas o cupones distintos
no pueden confirmarse entre sí. Las referencias históricas y equivalentes
generales permanecen limpias, sin flags de calidad.

Sí bloquean una alerta los problemas de identidad, vendedor, variante,
ubicación, base de precio, moneda, precio o stock, además de cualquier flag
desconocido. Un SKU agotado conserva su estado, pero su precio se descarta. Los
vendedores marketplace nunca se mezclan con el vendedor propio.

Para integrar otra tienda, consulta [Cómo añadir una tienda](docs/adding-a-store.md).
La operación y límites actuales están en
[Operación de la Fase 2](docs/phase2-operations.md).

## Límites y política

- Solo recursos públicos.
- Nunca login, carrito, checkout ni compras.
- `robots.txt` habilitado en Scrapy.
- Una solicitud concurrente por dominio y pausa entre solicitudes.
- Sin cookies, proxies rotativos ni evasión de identidad.
- Pausa inmediata ante HTTP 403, 429, 503, HTML de bloqueo o CAPTCHA.
- Circuito persistente por tienda y backoff por producto después de fallos.
- `User-Agent` propio y configurable.

Coolbox, Oechsle, Promart, Cassinelli, EFE, La Curacao, plazaVea, Topitop y Vega
son los nueve adapters habilitados. Marketplace, bases por peso o medida,
identidad ambigua y variantes incompatibles continúan bloqueados. Tottus queda
diferida por inestabilidad y ubicación; Hiraoka, Ripley, Tai Loy y Memory Kings
no se integran bajo las condiciones revisadas. Consulta
[la política de fuentes](docs/source-policy.md).

La detección automática no significa scraping universal. Solo reconoce dominios
de adapters registrados. Cada dominio nuevo necesita revisión de `robots.txt`,
términos y límites, además de parser, fixtures y pruebas propias. Cuando varias
tiendas comparten una plataforma como VTEX se puede reutilizar una base técnica,
pero siguen siendo necesarias la política y validación de cada dominio.

## Configuración

`.env` contiene la configuración local y no se guarda en Git. Para otra máquina,
crea el archivo solo si todavía no existe:

```bash
if [ ! -e .env ]; then
  cp .env.example .env
else
  echo ".env ya existe; no fue sobrescrito."
fi
```

Después se debe reemplazar la contraseña de ejemplo por una larga y aleatoria.
`.env.example` solo contiene marcadores públicos. Los secretos reales pertenecen
exclusivamente a `.env`, que no debe ejecutarse con `source`, publicarse ni
mostrarse en capturas.

Para comprobar qué política quedó activa sin revelar el token ni el chat de
Telegram:

```bash
uv run bot-ofertas config show
```

## Siguientes hitos

La Fase 4C ya deja el sistema operable de forma privada y económica en una sola
PC. No equivale todavía a un servicio público: el panel y la API solo escuchan
en `localhost`, y la disponibilidad depende de que esa PC, Docker Desktop e
Internet estén activos.

La Fase 6.2 amplía el descubrimiento a nueve tiendas y mejora la cobertura
efectiva: evita gastar cupo en publicaciones de Oechsle cuyo único stock actual
sea marketplace y permite alertas de Promart con un recordatorio explícito de
delivery. La Fase 6.1 registra suscriptores, pagos externos, renovaciones,
vencimientos y preparación del lanzamiento; las personas todavía se agregan y
retiran manualmente del canal. Los siguientes hitos son medir esta ampliación
durante el piloto, desplegar permanentemente y, si la beta lo justifica,
automatizar cobro y membresía. WhatsApp y correo podrán añadirse como canales
sobre el mismo contrato de notificaciones.
