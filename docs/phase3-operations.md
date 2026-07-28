# Operación de la Fase 3

Esta guía cubre el detector `phase3-v2`: ventanas históricas, equivalencias
verificadas, confianza y confirmación antes de enviar una alerta. Las reglas de
rastreo responsable, Telegram y recuperación de la Fase 1 siguen vigentes.

## Preparación

Desde Ubuntu/WSL, con Docker Desktop iniciado:

```bash
cd /mnt/c/Users/TU_USUARIO_WINDOWS/Documents/Proyectos/bot-ofertas
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/bot-ofertas"
docker compose up -d postgres
uv sync --locked
uv run bot-ofertas db upgrade
uv run bot-ofertas config show
```

`db upgrade` aplica la migración de Fase 3 sin borrar el historial anterior. El
head actual es `0008_conditioned_offers`. Las decisiones quedan identificadas
por versión de detector; la versión operativa de esta fase es `phase3-v2`.

`config show` presenta la política efectiva y solo indica si las credenciales de
Telegram están presentes. Nunca imprime el token ni el `chat_id`.

## Configuración

Los valores se colocan en `.env`, nunca en `.env.example`. Todos los campos
terminados en `PERCENT` reciben porcentajes; por ejemplo, `3` significa 3 % y no
0.03.

| Variable | Predeterminado | Función |
| --- | ---: | --- |
| `BOT_DETECTOR_VERSION` | `phase3-v2` | Versión con la que se registra cada decisión. Debe conservarse en `phase3-v2` mientras no exista otra versión implementada. |
| `BOT_DETECTION_HISTORY_LIMIT` | `2500` | Cantidad máxima de observaciones exactas que se carga por oferta. Es un límite de filas, no de días. |
| `BOT_DETECTION_HISTORY_DAYS` | `90` | Antigüedad máxima del historial cargado para las medianas. |
| `BOT_DETECTION_MIN_HISTORY_SAMPLES` | `3` | Muestras mínimas dentro de cada ventana para habilitar su mediana. |
| `BOT_EQUIVALENT_MAX_AGE_HOURS` | `24` | Frescura máxima de una observación equivalente de otra tienda. |
| `BOT_EQUIVALENT_LIMIT` | `20` | Máximo de tiendas equivalentes que puede usar una evaluación. |
| `BOT_DETECTION_MIN_EQUIVALENT_SAMPLES` | `2` | Mínimo de otras tiendas válidas para habilitar la mediana equivalente. |
| `BOT_CONFIRMATION_REQUIRED` | `true` | Exige una segunda observación independiente antes de alertar. |
| `BOT_CONFIRMATION_MAX_AGE_MINUTES` | `180` | Vigencia base de una candidata. La vigencia efectiva nunca es menor que dos intervalos del producto. |
| `BOT_CONFIRMATION_PRICE_TOLERANCE_PERCENT` | `3` | Diferencia máxima entre el primer precio candidato y el de confirmación. |
| `BOT_CONFIRMATION_CONFIDENCE_BONUS` | `20` | Puntos de confianza añadidos después de una confirmación válida. |
| `BOT_ALERT_MIN_CONFIDENCE` | `50` | Confianza final mínima para reservar una alerta. |
| `BOT_PRICE_ERROR_MIN_CORROBORATING_SIGNALS` | `2` | Familias independientes que deben respaldar un posible error de precio. |
| `BOT_PRICE_ERROR_MIN_CONFIDENCE` | `50` | Confianza base mínima para conservar la clasificación de posible error. |

Los umbrales de severidad existentes continúan en
`BOT_DEAL_GOOD_PERCENT`, `BOT_DEAL_EXCEPTIONAL_PERCENT` y
`BOT_DEAL_PRICE_ERROR_PERCENT`. La confianza no reemplaza estos umbrales:
severidad mide qué tan grande es la reducción y confianza mide cuánta evidencia
independiente la respalda.

Después de editar `.env`, valida los valores antes de iniciar el monitor:

```bash
uv run bot-ofertas config show
```

Un valor inválido detiene el comando con un error explícito. No copies tokens,
contraseñas ni identificadores privados en documentación, commits o capturas.

## Evidencia que utiliza el detector

El detector compara únicamente observaciones de la misma oferta exacta: tienda,
producto externo, SKU, vendedor, variante, condición y moneda. No mezcla
marketplace con vendedor propio ni accesorios, capacidades, colores o tamaños
distintos.

Para cada observación válida se evalúan:

- El precio válido inmediatamente anterior.
- La mediana de los 7 días anteriores.
- La mediana de los 30 días anteriores.
- La mediana de los 90 días anteriores.
- El mínimo válido de todo el historial comparable.
- La mediana de publicaciones equivalentes verificadas de otras tiendas.
- El precio de lista publicado en la observación actual.

Cada mediana temporal necesita el número configurado en
`BOT_DETECTION_MIN_HISTORY_SAMPLES` dentro de su propia ventana. Una ventana sin
suficientes muestras queda registrada, pero no influye en la clasificación. El
precio anterior sí puede usarse desde la primera muestra previa válida.

El precio de lista puede respaldar una oferta, pero por sí solo no demuestra un
posible error de precio. Esa clasificación exige las familias independientes y
la confianza indicadas en la configuración; si no las alcanza, se reduce a
`exceptional_deal`.

Las cuotas se almacenan separadas del precio total. Una cuota individual nunca
se usa como precio del producto ni como sustituto cuando falta el total.

Las condiciones comerciales de tarjeta o medio de pago, membresía, cupón,
cantidad mínima y promoción se conservan como información y no bloquean por sí
solas una candidata. `history` y `alert list` las muestran bajo `Condiciones`, y
Telegram las incluye antes de la comparación para que el usuario sepa qué debe
cumplir.

El parser también calcula una huella SHA-256 opaca a partir de la evidencia
promocional exacta. Esa huella no revela el texto original, pero separa tarjetas,
programas, cupones o cantidades diferentes dentro de una misma familia. Una
observación antigua sin esa huella solo puede confirmarse si se repite exactamente
el mismo payload público.

La política distingue esas condiciones de los errores que sí impiden comparar.
Siguen bloqueando:

- identidad de producto, vendedor o variante dudosa;
- ubicación sin verificar cuando modifica precio o stock;
- base de precio incompatible, por ejemplo peso, superficie o multiplicador;
- moneda inválida o distinta de PEN;
- precio total ausente o inválido;
- producto agotado o stock incoherente;
- una cuota individual detectada como supuesto precio total;
- cualquier flag desconocido.

Una cantidad disponible centinela solo indica que el número exacto de unidades
no es confiable. Un precio de lista no positivo o menor que el precio actual
desactiva únicamente la señal de precio de lista; no invalida un precio total
que sí sea correcto.

Las referencias históricas y equivalentes generales se mantienen limpias: solo
observaciones sin flags de calidad pueden formar sus medianas o mínimos. Una
oferta condicionada puede compararse contra esas referencias limpias, pero no se
convierte en referencia general para otra oferta. Promart continúa como fuente
de historial mientras no exista un contexto de ubicación verificable.

## Seleccionar una variante exacta

Consulta los identificadores de productos:

```bash
uv run bot-ofertas product list
```

Si una ficha contiene varias variantes, selecciona explícitamente la que se
quiere seguir:

```bash
uv run bot-ofertas product variant PRODUCTO_ID \
  --variant "Color=Negro" \
  --variant "Capacidad=128 GB"
```

Repite `--variant` una vez por atributo. Las claves y valores se normalizan antes
de guardarse. Mientras una ficha ambigua no tenga una variante seleccionada, sus
observaciones se conservan pero el detector no genera alertas para ellas.

## Administrar equivalencias

Una equivalencia no se descubre ni se aprueba automáticamente. Antes de crearla,
una persona debe comprobar en las fichas públicas que las publicaciones tienen:

- La misma marca y el mismo modelo.
- La misma capacidad, color, tamaño y demás atributos relevantes.
- La misma condición y contenido del paquete.
- El producto principal en ambos casos, no un accesorio o repuesto.
- Un precio total comparable, sin confundir cuotas o condiciones de pago.

Los productos deben haberse registrado con `--brand`, `--model` y la variante
exacta. También se puede corregir la variante con `product variant`.

Crear un grupo canónico:

```bash
uv run bot-ofertas equivalence create \
  --name "Audífonos Ejemplo X1 negros" \
  --brand "Ejemplo" \
  --model "X1" \
  --variant "Color=Negro"
```

El comando devuelve `GRUPO_ID`. Consulta grupos y miembros:

```bash
uv run bot-ofertas equivalence list
```

Agregar publicaciones ya verificadas:

```bash
uv run bot-ofertas equivalence add-product GRUPO_ID PRODUCTO_ID
```

Retirar una asociación incorrecta:

```bash
uv run bot-ofertas equivalence remove-product GRUPO_ID PRODUCTO_ID
```

El sistema exige coincidencia de marca, modelo y variante, impide que un producto
pertenezca a más de un grupo y admite como máximo una publicación por tienda en
cada grupo. Durante el análisis toma como máximo la observación válida más
reciente de cada otra tienda; las publicaciones frecuentes de una sola tienda no
obtienen más peso.

Las referencias equivalentes también deben estar vigentes, en stock, en la misma
moneda y condición, ser del vendedor propio y no tener flags de calidad. Esta
exigencia mantiene limpia la referencia general; no significa que una condición
comercial bloquee la oferta actual. Si no se alcanza
`BOT_DETECTION_MIN_EQUIVALENT_SAMPLES`, esa señal queda inactiva y las demás
señales históricas continúan funcionando.

## Confirmación en una segunda ejecución

La confirmación predeterminada es deliberadamente temporal:

```text
Primera ejecución
  -> nueva observación califica como oferta
  -> se crea una candidata en espera
  -> no se crea entrega de Telegram

Transcurre el intervalo configurado del producto
  -> otra ejecución realiza un rastreo público independiente
  -> el precio sigue calificando y conserva la misma familia y huella exacta
     comerciales y está dentro de la tolerancia
  -> aumenta la confianza y se confirma
  -> deduplicación reserva una única entrega
  -> Telegram puede enviarla
```

Una segunda llamada inmediata a `analyze` no sirve: necesita una nueva
observación de otro rastreo. Tampoco sirve ejecutar `crawl --force` antes de
tiempo. Aunque `--force` permite una prueba manual de rastreo, la confirmación
siempre respeta como mínimo el `check_interval_minutes` del producto y nunca usa
dos observaciones de la misma corrida.

Las familias comerciales forman parte de la identidad de confirmación y
deduplicación. Por ejemplo, una observación con precio de membresía solo puede
confirmarse con otra observación de membresía; una lectura normal o condicionada
a tarjeta no la confirma. Cuando aparecen varias condiciones, debe repetirse el
mismo conjunto de familias.

Para probar el flujo manualmente:

```bash
uv run bot-ofertas run --once
uv run bot-ofertas confirmation list --limit 20
```

Espera el intervalo del producto —60 minutos por defecto— y ejecuta:

```bash
uv run bot-ofertas run --once
uv run bot-ofertas alert list --limit 20
```

En uso normal basta mantener:

```bash
uv run bot-ofertas run
```

El scheduler revisa periódicamente qué productos ya están vencidos; no consulta
una tienda antes de su intervalo. Si el segundo precio se aparta más que
`BOT_CONFIRMATION_PRICE_TOLERANCE_PERCENT`, reemplaza la candidata y comienza una
nueva espera. Si deja de ser oferta, se agota, cambia de identidad o vence su
ventana, no se envía la alerta.

La vigencia efectiva de una candidata es el mayor valor entre
`BOT_CONFIRMATION_MAX_AGE_MINUTES` y dos veces el intervalo del producto. Esto
evita que un producto con una frecuencia lenta expire antes de tener una
oportunidad razonable de confirmación.

`BOT_CONFIRMATION_REQUIRED=false` existe para diagnóstico controlado. No es la
configuración recomendada para producción porque permite que una sola lectura
reserve una alerta.

## Consultar resultados

Mostrar la política activa:

```bash
uv run bot-ofertas config show
```

Ver candidatas todavía activas:

```bash
uv run bot-ofertas confirmation list --limit 20
```

Ver ofertas, su severidad, confianza, confirmación y versión del detector:

```bash
uv run bot-ofertas alert list --limit 20
```

Incluir descartes y decisiones sin oferta:

```bash
uv run bot-ofertas alert list --all --limit 50
```

Ejecutar etapas por separado:

```bash
uv run bot-ofertas crawl
uv run bot-ofertas analyze
uv run bot-ofertas notify
```

`run --once` ejecuta esas tres etapas en orden. Una candidata en espera no crea
una entrega, por lo que `notify` no tiene nada que enviar hasta que otra
observación válida la confirme y alcance `BOT_ALERT_MIN_CONFIDENCE`.

## Diagnóstico

### La candidata permanece esperando

Comprueba:

1. Que haya transcurrido el intervalo completo del producto.
2. Que una nueva ejecución haya guardado otra observación.
3. Que la tienda no esté pausada por bloqueo o CAPTCHA.
4. Que el producto continúe activo, en stock y con la misma identidad.
5. Que el nuevo precio permanezca dentro de la tolerancia configurada.

`confirmation list` muestra solo estados activos. `alert list --all` permite
revisar decisiones que quedaron reemplazadas, expiradas o descartadas.

### No aparece la referencia equivalente

Ejecuta:

```bash
uv run bot-ofertas product list
uv run bot-ofertas equivalence list
```

Verifica la marca, el modelo y la variante exacta, que no haya dos miembros de la
misma tienda, que existan suficientes tiendas distintas y que sus observaciones
no superen `BOT_EQUIVALENT_MAX_AGE_HOURS`.

### Hay oferta, pero no alerta

Revisa en `alert list --all`:

- `Confianza`: puede estar debajo de `BOT_ALERT_MIN_CONFIDENCE`.
- `Confirmación`: puede seguir en espera.
- `Condiciones`: informa tarjeta, membresía, cupón, cantidad mínima o promoción;
  no es un descarte por sí sola.
- `Descartes`: puede indicar identidad, variante, marketplace, condición del
  producto, ubicación, base de precio, moneda, disponibilidad o un flag
  desconocido.
- `Alerta`: puede estar suprimida por deduplicación o cooldown.

Si la alerta está pendiente, valida Telegram según
[Operación de la Fase 1](phase1-operations.md).

## Verificación

La prueba completa del proyecto sigue siendo:

```bash
uv run pytest -q -p no:cacheprovider
RUN_POSTGRES_TESTS=1 uv run pytest -q -p no:cacheprovider
uv run ruff check .
```

Estas pruebas cubren las ventanas históricas, la selección de variante, las
equivalencias, la confianza, los precios condicionados, la confirmación durable,
la deduplicación y la persistencia en PostgreSQL.
