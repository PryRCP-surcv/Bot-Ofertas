# Bot de ofertas

Monitor responsable de precios públicos para tiendas online de Perú. El objetivo
es conservar historial por SKU, variante y vendedor para detectar
ofertas excepcionales y posibles errores de precio sin realizar compras.

## Estado actual

Las Fases 1 y 2 están implementadas y probadas en ejecución local:

1. Se registra una URL pública de producto.
2. El registro de tiendas reconoce el dominio, elige el adapter habilitado y
   normaliza la URL. El usuario no escribe manualmente el nombre de la tienda.
3. Scrapy verifica y obedece `robots.txt`.
4. El spider de esa tienda consulta únicamente recursos públicos permitidos.
5. Cada combinación SKU + vendedor se normaliza de forma independiente.
6. Un pipeline común valida el resultado y PostgreSQL conserva la ejecución y
   la observación de precio.
7. El detector compara precio anterior, mediana, mínimo histórico y precio de
   lista, conservando señales y motivos.
8. Una capa persistente elimina alertas repetidas y aplica reintentos.
9. Telegram recibe las ofertas cuando sus credenciales están configuradas.
10. Un scheduler local ejecuta el ciclo completo sin solapar corridas.

La primera prueba de la Fase 1 guardó correctamente una barra de sonido a
`PEN 179.00`, con precio de lista `PEN 499.00`, disponibilidad y vendedor.
La validación viva de la Fase 2 guardó después una observación de Oechsle y otra
de Promart, sin errores.

Coolbox, Oechsle y Promart están habilitadas. Oechsle opera como piloto de
alertas y Promart como piloto de historial: sus alertas quedan bloqueadas hasta
modelar una ubicación verificable. Ambas se limitan a fichas agregadas
manualmente, un mínimo de 60 minutos y un máximo de 5 URLs por tienda y corrida.
Comparten un parser VTEX reutilizable, pero conservan política, dominios,
vendedores, fixtures y pruebas propios.

El detector, la deduplicación, Telegram y el scheduler ya están implementados.
La siguiente fase mejorará la precisión y la confirmación de candidatos. Aún no
existen dashboard web, WhatsApp, Gmail ni despliegue permanente en un servidor.

Telegram es actualmente un canal de salida: envía alertas, pero todavía no
responde `/start`, `/ofertas`, `Hola` ni otros comandos. El monitoreo continuo
solo funciona mientras `uv run bot-ofertas run` permanezca activo.

## Dónde está cada cosa

- Código y documentación: la carpeta donde se clonó este repositorio en Windows.
- Esa misma carpeta desde Ubuntu/WSL:
  `/mnt/c/Users/TU_USUARIO_WINDOWS/Documents/Proyectos/bot-ofertas`
- Entorno Python, dentro de Ubuntu:
  `$HOME/.venvs/bot-ofertas`
- PostgreSQL, dentro de Docker Desktop:
  contenedor `bot-ofertas-postgres`
- Datos de PostgreSQL:
  volumen persistente `bot-ofertas_postgres_data`

Apagar la PC no elimina el proyecto ni el historial, pero sí detiene
temporalmente los rastreos y las alertas. Después de reiniciar hay que volver a
iniciar el monitor.

## Volver a ejecutarlo después de reiniciar

1. Abre Docker Desktop y espera a que indique **Engine running**.
2. Abre Ubuntu desde Windows Terminal.
3. Ejecuta:

```bash
cd /mnt/c/Users/TU_USUARIO_WINDOWS/Documents/Proyectos/bot-ofertas
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/bot-ofertas"
docker compose up -d postgres
uv sync --locked
uv run bot-ofertas db upgrade
```

Comprueba el estado:

```bash
docker compose ps
uv run bot-ofertas store list
uv run bot-ofertas product list
uv run bot-ofertas history
```

Para mantener el monitor activo después de comprobar el estado:

```bash
uv run bot-ofertas run
```

En esta computadora PostgreSQL usa el puerto `5433` del host porque el `5432`
ya estaba ocupado. El valor real se conserva en `.env`.

## Uso

Ver las tiendas registradas, sus dominios y si están habilitadas:

```bash
uv run bot-ofertas store list
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
```

Existe `crawl --force` para pruebas manuales, pero no debe usarse repetidamente.
El límite por ejecución es 20 URLs y el intervalo mínimo aceptado es 30 minutos.

La guía completa de configuración, Telegram, estados, deduplicación y
recuperación está en [Operación de la Fase 1](docs/phase1-operations.md).

Detener PostgreSQL sin perder el historial:

```bash
docker compose stop postgres
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

Las pruebas de PostgreSQL utilizan datos temporales y los revierten o eliminan
al terminar.

Revisión estática:

```bash
uv run ruff check .
```

El workflow de GitHub Actions ejecuta Ruff, las pruebas unitarias, todas las
migraciones y las pruebas de integración con un PostgreSQL efímero en cada
`push` a `main` y en cada pull request. Telegram permanece desactivado en CI.

## Arquitectura multi-tienda

```text
URL registrada
  -> StoreRegistry: detecta dominio y normaliza URL
  -> tracked_products
  -> claim_due: lease PostgreSQL
  -> adapter/spider correspondiente
  -> normalización por SKU + vendedor
  -> validación PriceObservation
  -> pipeline PostgreSQL común
  -> historial inmutable
  -> DealDetector puro
  -> deduplicación persistente
  -> delivery Telegram con lease y backoff
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
- `deal_detections`: decisión, puntuación, señales, referencias y descartes por
  observación.
- `offer_alert_states`: ventana de deduplicación por oferta exacta.
- `notification_deliveries`: entregas Telegram, leases, intentos y errores
  sanitizados.

El precio total y las cuotas son campos distintos. Un SKU agotado puede conservar
su estado, pero su precio centinela se descarta. Los vendedores marketplace nunca
se mezclan con el vendedor propio.

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

Coolbox, Oechsle y Promart son los tres pilotos habilitados; Promart construye
historial, pero no alerta mientras su ubicación sea desconocida. plazaVea queda
diferida por precios por peso, ubicación y vendedores; Hiraoka, Ripley, Tai Loy
y Memory Kings no se integran bajo las condiciones revisadas. Consulta
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

## Siguientes hitos

La Fase 3 mejorará medianas de 7, 30 y 90 días, puntuación de confianza,
comparación de equivalentes y segunda comprobación antes de alertar. Después
vendrán la API y el panel de administración. WhatsApp y correo serán canales
adicionales sobre el mismo contrato de notificaciones.
