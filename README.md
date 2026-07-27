# Bot de ofertas

Monitor responsable de precios públicos para tiendas online de Perú. El objetivo
es conservar historial por SKU, variante y vendedor para detectar posteriormente
ofertas excepcionales y posibles errores de precio sin realizar compras.

## Estado actual

El primer flujo funcional y la base multi-tienda están listos:

1. Se registra una URL pública de producto.
2. El registro de tiendas reconoce el dominio, elige el adapter habilitado y
   normaliza la URL. El usuario no escribe manualmente el nombre de la tienda.
3. Scrapy verifica y obedece `robots.txt`.
4. El spider de esa tienda consulta únicamente recursos públicos permitidos.
5. Cada combinación SKU + vendedor se normaliza de forma independiente.
6. Un pipeline común valida el resultado y PostgreSQL conserva la ejecución y
   la observación de precio.

La primera prueba controlada guardó correctamente una barra de sonido a
`PEN 179.00`, con precio de lista `PEN 499.00`, disponibilidad y vendedor.

Coolbox es la única tienda habilitada hoy. La arquitectura ya permite incorporar
otras tiendas sin acoplar la CLI, el pipeline ni el esquema de historial a
Coolbox.

Todavía no están implementados el detector estadístico, las alertas ni el
servicio que programa ejecuciones automáticamente. Esos son los siguientes
módulos.

## Dónde está cada cosa

- Código y documentación, en Windows:
  `C:\Users\SURICH\Documents\Proyectos\bot-ofertas`
- La misma carpeta vista desde Ubuntu:
  `/mnt/c/Users/SURICH/Documents/Proyectos/bot-ofertas`
- Entorno Python, dentro de Ubuntu:
  `$HOME/.venvs/bot-ofertas`
- PostgreSQL, dentro de Docker Desktop:
  contenedor `bot-ofertas-postgres`
- Datos de PostgreSQL:
  volumen persistente `bot-ofertas_postgres_data`

Apagar la PC no elimina el proyecto ni el historial.

## Volver a ejecutarlo después de reiniciar

1. Abre Docker Desktop y espera a que indique **Engine running**.
2. Abre Ubuntu desde Windows Terminal.
3. Ejecuta:

```bash
cd /mnt/c/Users/SURICH/Documents/Proyectos/bot-ofertas
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

Consultar solo los productos cuyo intervalo ya venció:

```bash
uv run bot-ofertas crawl
```

Ver el historial reciente:

```bash
uv run bot-ofertas history --limit 20
```

Existe `crawl --force` para pruebas manuales, pero no debe usarse repetidamente.
El límite por ejecución es 20 URLs y el intervalo mínimo aceptado es 30 minutos.

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

La prueba de PostgreSQL revierte sus datos al terminar.

Revisión estática:

```bash
uv run ruff check .
```

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
  -> historial consultable
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

El precio total y las cuotas son campos distintos. Un SKU agotado puede conservar
su estado, pero su precio centinela se descarta. Los vendedores marketplace nunca
se mezclan con el vendedor propio.

Para integrar otra tienda, consulta [Cómo añadir una tienda](docs/adding-a-store.md).

## Límites y política

- Solo recursos públicos.
- Nunca login, carrito, checkout ni compras.
- `robots.txt` habilitado en Scrapy.
- Una solicitud concurrente por dominio y pausa entre solicitudes.
- Sin cookies, proxies rotativos ni evasión de identidad.
- Pausa inmediata ante HTTP 403, 429, 503, HTML de bloqueo o CAPTCHA.
- Circuito persistente por tienda y backoff por producto después de fallos.
- `User-Agent` propio y configurable.

Coolbox es la única tienda habilitada por ahora. Oechsle es candidata para la
segunda integración. Hiraoka y Ripley permanecen deshabilitadas por sus
restricciones actuales. Consulta [la política de fuentes](docs/source-policy.md).

La detección automática no significa scraping universal. Solo reconoce dominios
de adapters registrados. Cada dominio nuevo necesita revisión de `robots.txt`,
términos y límites, además de parser, fixtures y pruebas propias. Cuando varias
tiendas comparten una plataforma como VTEX se puede reutilizar una base técnica,
pero siguen siendo necesarias la política y validación de cada dominio.

## Configuración

`.env` contiene la configuración local y no se guarda en Git. Para otra máquina:

```bash
cp .env.example .env
```

Después se debe reemplazar la contraseña de ejemplo por una larga y aleatoria.
Nunca publiques ni pegues el contenido real de `.env`.

## Siguientes hitos

Construir el detector con varias señales y estados auditables:

- caída frente al historial del mismo SKU y vendedor;
- desviación frente a mediana móvil;
- descuento contra precio de lista como señal secundaria;
- exclusión de cuotas, agotados, accesorios, variantes, marketplace y
  condiciones distintas;
- confirmación en una segunda consulta antes de alertar;
- clasificación `oferta fuerte` o `posible error`, nunca certeza absoluta.

Después se incorporarán los canales de alerta (Telegram, WhatsApp o correo) y un
scheduler que ejecute workers automáticamente. Actualmente `crawl` se inicia de
forma manual, aunque su sistema de leases ya está preparado para múltiples
workers.
