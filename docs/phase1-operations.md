# Operación de la Fase 1

La Fase 1 ejecuta el flujo completo sin comprar, iniciar sesión ni agregar
productos al carrito:

```text
producto registrado
  -> scheduler local
  -> Scrapy consulta una URL pública revisada
  -> PostgreSQL guarda la observación
  -> detector valida y compara el historial
  -> deduplicador reserva una alerta
  -> Telegram entrega o reintenta
```

## 1. Preparar el entorno después de reiniciar la PC

Abre Docker Desktop y espera a que muestre **Engine running**. Después abre
Ubuntu desde Windows Terminal:

```bash
cd /mnt/c/Users/TU_USUARIO_WINDOWS/Documents/Proyectos/bot-ofertas
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/bot-ofertas"
docker compose up -d postgres
uv sync --locked
uv run bot-ofertas db upgrade
```

## 2. Registrar y administrar productos

La marca, el modelo y la variante son restricciones reales del detector. La
tienda se reconoce por el dominio:

```bash
uv run bot-ofertas product add \
  "https://www.coolbox.pe/barra-sonido-decibel-bluetooth-100w-negro-mel-s25/p" \
  --label "Barra de sonido Decibel S25" \
  --brand "Decibel" \
  --model "S25" \
  --variant "Color=Negro" \
  --interval 60
```

Si el producto buscado es intencionalmente un accesorio, añade `--accessory`.
Sin esa opción, títulos como cable, cargador, funda o soporte no generan alertas.
Cuando no se declara `--variant`, la primera variante observada se conserva como
la esperada para las siguientes consultas.

```bash
uv run bot-ofertas product list
uv run bot-ofertas product disable UUID_DEL_PRODUCTO
uv run bot-ofertas product enable UUID_DEL_PRODUCTO
```

Desactivar un producto conserva todo su historial.

## 3. Configurar Telegram

1. En Telegram abre el bot oficial **@BotFather**.
2. Ejecuta `/newbot` y conserva el token como un secreto.
3. Abre el bot recién creado y envíale `/start`.

El bot de la Fase 1 es únicamente un canal de salida: `/start` habilita la
conversación, pero el bot todavía no responde comandos ni mensajes.

4. Guarda el token únicamente en `.env`, inicialmente con el identificador
   vacío:

```dotenv
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=token_entregado_por_BotFather
TELEGRAM_CHAT_ID=
TELEGRAM_FREE_CHAT_ID=
TELEGRAM_VIP_CHAT_ID=
TELEGRAM_VIP_MIRROR_ENABLED=true
TELEGRAM_OPERATIONS_CHAT_ID=
```

Para conocer el `chat_id`, consulta las actualizaciones sin ejecutar `.env` como
si fuera un script de Bash. Este comando lee el token localmente y muestra
únicamente los identificadores de los chats que escribieron al bot:

```bash
uv run python - <<'PY'
import json
from urllib.request import urlopen

from dotenv import dotenv_values

token = (dotenv_values(".env").get("TELEGRAM_BOT_TOKEN") or "").strip()
if not token:
    raise SystemExit("Falta TELEGRAM_BOT_TOKEN en .env")

try:
    with urlopen(
        f"https://api.telegram.org/bot{token}/getUpdates",
        timeout=10,
    ) as response:
        updates = json.load(response).get("result", [])
except Exception:
    raise SystemExit("Telegram rechazó la consulta; revisa el token sin mostrarlo.")

chat_ids = {
    str(message["chat"]["id"])
    for update in updates
    if (message := update.get("message")) and message.get("chat")
}
print("\n".join(sorted(chat_ids)) or "Envía /start al bot y vuelve a intentarlo.")
PY
```

Guarda el número obtenido como `TELEGRAM_FREE_CHAT_ID`. Si la instalación ya
usa `TELEGRAM_CHAT_ID`, no es obligatorio cambiarlo: funciona como fallback del
canal Free. `TELEGRAM_VIP_CHAT_ID` y `TELEGRAM_OPERATIONS_CHAT_ID` son
opcionales. Nunca compartas `.env`, el
mensaje de BotFather, una captura que contenga el token ni una URL de la API que
lo incluya. Si un token se expone, genera uno nuevo inmediatamente desde
BotFather con `/token`.

Con Telegram aún sin configurar, el rastreo y la detección siguen funcionando y
las entregas quedan pendientes:

```bash
uv run bot-ofertas notify
```

`notify` realiza envíos reales de las alertas pendientes cuando Telegram está
configurado.

Las observaciones nuevas guardan la imagen pública HTTPS informada por la
tienda. Si una oferta confirmada tiene imagen, Telegram la envía como foto con
una descripción y un botón a la ficha; si Telegram rechaza la foto, el mismo
intento continúa con el mensaje de texto para no perder la alerta.

## 4. Ejecutar el monitor

Un ciclo completo, útil para comprobar la instalación:

```bash
uv run bot-ofertas run --once
```

Ejecución continua:

```bash
uv run bot-ofertas run
```

El scheduler despierta cada cinco minutos de forma predeterminada, pero Scrapy
solo consulta productos cuyo intervalo haya vencido. La terminal debe permanecer
abierta. Detén el proceso de forma segura con `Ctrl+C`. Suspender o apagar la PC
detiene el monitor, y la Fase 1 todavía no lo inicia automáticamente con Windows.

También pueden ejecutarse las etapas por separado:

```bash
uv run bot-ofertas crawl
uv run bot-ofertas analyze
uv run bot-ofertas notify
```

`run` ejecuta cada ciclo en un proceso aislado. Esto permite que Scrapy termine
su reactor y evita solapamientos; un error de un ciclo queda registrado y el
scheduler continúa con el siguiente.

## 5. Ver resultados

```bash
uv run bot-ofertas history --limit 20
uv run bot-ofertas alert list --limit 20
uv run bot-ofertas alert list --all --limit 20
```

`history` muestra las observaciones sin decidir si son ofertas. `alert list`
muestra clasificación, puntuación, referencia utilizada, motivos y estado de la
entrega. La opción `--all` incluye descartes y errores de procesamiento
aislados.

Estados habituales:

- `pending`: reservada para Telegram.
- `retrying`: Telegram falló temporalmente y se aplicó backoff.
- `sent`: Telegram confirmó el mensaje.
- `suppressed`: era una oferta, pero ya se había alertado recientemente.
- `failed`: agotó el máximo de intentos.

Una observación malformada se conserva como `processing_error` en vez de
bloquear la cola. Cada etapa del ciclo está aislada: aunque el rastreo o una
decisión fallen, el sistema todavía intenta despachar alertas que ya estaban
pendientes.

El análisis admite 1 000 observaciones por ciclo de forma predeterminada,
configurables con `BOT_ANALYSIS_LIMIT` entre 100 y 5 000. Primero procesa la
captura más reciente de cada producto y después consume el historial pendiente.
Así, una ampliación del catálogo no deja las ofertas nuevas detenidas detrás de
una cola antigua. El panel **Distribución** muestra cantidad pendiente,
antigüedad de la observación más antigua y ciclos estimados para vaciarla.

Una cola histórica puede tardar varios ciclos en llegar a cero sin afectar los
nuevos avisos. Una oferta todavía requiere una segunda observación independiente
para confirmarse; aumentar la capacidad no elimina esa protección.

## 6. Cómo decide

Esta sección conserva la explicación del detector inicial. La política vigente,
incluidas las ventanas, confianza, condiciones comerciales y confirmación, está
en [Operación de la Fase 3](phase3-operations.md).

La política predeterminada clasifica una reducción como:

- `good_deal`: 20 % o más.
- `exceptional_deal`: 40 % o más.
- `possible_price_error`: 70 % o más.

Evalúa cuatro referencias de forma independiente:

- precio anterior;
- mediana histórica;
- mínimo histórico;
- precio de lista publicado.

Las señales históricas requieren tres muestras comparables. El precio de lista
puede producir una decisión desde la primera observación. “Posible error” es una
clasificación preventiva, nunca una afirmación de que la tienda respetará el
precio.

El mínimo histórico es una referencia de comparación. Un nuevo mínimo solo
genera una alerta si la reducción alcanza al menos el umbral configurado; no se
alerta por cualquier variación pequeña.

No se alerta cuando:

- la moneda no es PEN;
- no hay precio total positivo;
- el producto no está disponible;
- el precio coincide con una cuota;
- la oferta pertenece a marketplace;
- la condición no es nueva;
- hay un flag bloqueante o desconocido;
- la marca, modelo, variante o tipo accesorio no coinciden.

Los indicadores de tarjeta o medio de pago, membresía, cupón, cantidad mínima y
promoción son condiciones informativas en `phase3-v2`: se muestran en la alerta
y no la bloquean por sí solos. Deben repetirse en la segunda observación de
confirmación. Una cuota individual permanece separada y nunca se usa como precio
total.

Las comparaciones históricas se limitan al mismo producto rastreado, tienda,
producto externo, SKU, vendedor, variante, condición y moneda.

## 7. Deduplicación y reintentos

La identidad de deduplicación incluye canal, producto, tienda, SKU, vendedor,
variante, condición, moneda, las familias comerciales y una huella opaca de sus
condiciones exactas. Una oferta continua se envía una sola vez y no vuelve a
notificarse solo porque hayan pasado 24 horas. Durante el mismo episodio solo
se reserva otra alerta si:

- aumente la severidad; o
- el precio baje otro 5 % como mínimo.

El episodio se cierra cuando una observación válida deja de ser oferta, cambia
la condición comercial activa o el producto vuelve a su precio normal. Si la
oferta reaparece después, puede generar una nueva alerta una vez cumplida la
espera configurada por `BOT_ALERT_COOLDOWN_HOURS`. Esa espera evita mensajes
repetidos si una tienda alterna precios durante un periodo corto.

Las entregas usan leases en PostgreSQL para que varios workers no reclamen el
mismo mensaje. Un fallo temporal se reintenta con backoff exponencial hasta cinco
intentos. `notification_deliveries` es la fuente de verdad por canal; el estado
guardado en la detección es un resumen operativo de la Fase 1. Como Telegram es
un sistema externo, existe una pequeña posibilidad de entrega duplicada si el
proceso termina después de que Telegram acepte el mensaje pero antes de guardar
la confirmación local. Cada mensaje incluye una referencia interna para poder
reconocer ese caso.

## 8. Configuración

Todos estos valores son opcionales y aparecen documentados en `.env.example`:

```dotenv
BOT_DETECTOR_VERSION=phase3-v2
BOT_SCHEDULER_POLL_SECONDS=300
BOT_DETECTION_HISTORY_LIMIT=2500
BOT_DETECTION_HISTORY_DAYS=90
BOT_DETECTION_MIN_HISTORY_SAMPLES=3
BOT_DEAL_GOOD_PERCENT=20
BOT_DEAL_EXCEPTIONAL_PERCENT=40
BOT_DEAL_PRICE_ERROR_PERCENT=70
BOT_ALERT_COOLDOWN_HOURS=24
BOT_ALERT_SIGNIFICANT_IMPROVEMENT_PERCENT=5
BOT_NOTIFICATION_MAX_ATTEMPTS=5
BOT_NOTIFICATION_RETRY_BASE_SECONDS=300
```

Los porcentajes deben conservar el orden: buena oferta, oferta excepcional y
posible error.

## 9. Verificación

```bash
uv run ruff check .
uv run pytest -q -p no:cacheprovider
RUN_POSTGRES_TESTS=1 uv run pytest -q -p no:cacheprovider
uv run alembic check
```

Ejecuta las pruebas de integración únicamente contra PostgreSQL local de
desarrollo; nunca contra una base de producción.

Las pruebas de Telegram usan un transporte simulado y nunca envían mensajes
reales.

El workflow `.github/workflows/ci.yml` repite Ruff, migraciones y toda la suite
con un PostgreSQL aislado en cada `push` a `main` y en cada pull request. No lee
el `.env` local ni utiliza las credenciales reales de Telegram.
