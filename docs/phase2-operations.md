# Operación de la Fase 2

La Fase 2 incorpora tiendas mediante adapters independientes. El registro
detecta la tienda por el dominio exacto de una URL, pero no intenta comprender
cualquier ecommerce ni descubrir tiendas automáticamente.

Al 28 de julio de 2026:

- Coolbox está registrada y habilitada.
- Oechsle está registrada y habilitada como piloto acotado.
- Promart está habilitada para construir historial, con alertas bloqueadas hasta
  modelar una ubicación verificable.
- plazaVea está diferida.
- Hiraoka, Ripley, Tai Loy y Memory Kings no deben integrarse.

Las decisiones y fuentes oficiales están en
[la política de fuentes](source-policy.md).

El primer rastreo vivo controlado de Oechsle y Promart se completó el 28 de
julio de 2026: una ficha por tienda, una observación persistida por ficha y cero
errores. Los productos usados para esa validación quedaron desactivados después
de la prueba; deben agregarse o activarse únicamente productos que realmente se
quieran vigilar.

## 1. Preparar y listar tiendas

Con PostgreSQL local iniciado y las migraciones al día:

```bash
docker compose up -d postgres
uv sync --locked
uv run bot-ofertas db upgrade
uv run bot-ofertas store list
```

`store list` muestra los adapters registrados, sus dominios, si están
habilitados, el intervalo mínimo y el máximo de productos por corrida. Una
tienda evaluada en la política no aparecerá aquí hasta que exista un adapter.

Un adapter deshabilitado puede aparecer en la lista, pero la CLI rechazará sus
URLs. Esto es intencional: documentar o registrar una tienda no autoriza su
rastreo.

## 2. Agregar una URL manual

Usa siempre la ficha pública exacta del producto, no una categoría, búsqueda,
carrito ni URL de checkout. Para Coolbox, Oechsle y Promart, la ruta aceptada
termina en `/p`.

La forma general es:

```bash
uv run bot-ofertas product add \
  "URL_HTTPS_REAL_DE_LA_FICHA_TERMINADA_EN_/p" \
  --label "Nombre reconocible" \
  --brand "Marca esperada" \
  --model "Modelo esperado" \
  --variant "Color=Valor esperado" \
  --interval 60
```

`--variant` puede repetirse. Si se quiere vigilar intencionalmente un accesorio,
se debe añadir `--accessory`; sin esa confirmación, el detector rechaza cables,
cargadores, fundas, soportes y otros accesorios.

### Coolbox

Coolbox se puede registrar actualmente:

```bash
uv run bot-ofertas product add \
  "URL_HTTPS_REAL_DE_COOLBOX_TERMINADA_EN_/p" \
  --label "Producto Coolbox" \
  --brand "Marca esperada" \
  --model "Modelo esperado" \
  --interval 60
```

Aunque su política técnica admite 30 minutos, se recomienda 60 minutos durante
el piloto.

### Oechsle

Oechsle exige 60 minutos y un máximo de 5 URLs por corrida:

```bash
uv run bot-ofertas product add \
  "URL_HTTPS_REAL_DE_OECHSLE_TERMINADA_EN_/p" \
  --label "Producto Oechsle" \
  --brand "Marca esperada" \
  --model "Modelo esperado" \
  --interval 60
```

Empieza con una URL y amplía el lote solo después de revisar el vendedor, SKU,
variante, moneda, disponibilidad y flags de calidad.

### Promart

Promart también exige un mínimo de 60 minutos y un máximo de 5 URLs por corrida:

```bash
uv run bot-ofertas product add \
  "URL_HTTPS_REAL_DE_PROMART_TERMINADA_EN_/p" \
  --label "Producto Promart de unidad fija" \
  --brand "Marca esperada" \
  --model "Modelo esperado" \
  --interval 60
```

El parser solo acepta como base verificable una unidad con multiplicador `1`.
Una unidad ausente, por peso, superficie, longitud o con otro multiplicador
recibe `unsupported_price_basis`, que sí bloquea por no ser comparable. Las
promociones condicionadas reciben flags informativos y pueden alertar mostrando
sus condiciones. Sin embargo, mientras no exista una ubicación verificable,
todas las observaciones Promart reciben `location_context_unverified`: se
guardan para historial, pero no generan alertas.

Para revisar lo registrado:

```bash
uv run bot-ofertas product list
```

## 3. Límites operativos

| Tienda | Estado actual | Intervalo mínimo | Máximo por corrida |
|---|---|---:|---:|
| Coolbox | Habilitada | 30 minutos en código; 60 recomendados | 20 en código; usar lotes pequeños en el piloto |
| Oechsle | Habilitada | 60 minutos | 5 URLs explícitas |
| Promart | Historial habilitado; alertas bloqueadas por ubicación | 60 minutos | 5 URLs explícitas |

Además se aplican estos límites comunes:

- una solicitud concurrente por dominio;
- demora base de 10 segundos, aleatorización y `AutoThrottle`;
- cookies deshabilitadas;
- una sola repetición para un grupo reducido de fallos transitorios;
- ninguna repetición automática para HTTP 403, 429 o 503;
- máximo global de 20 productos para `crawl`, sin superar el límite menor de
  cada tienda;
- solo tiendas y productos habilitados, con lease vigente en PostgreSQL.

`--force` omite únicamente el vencimiento del intervalo. No omite el límite por
tienda, el requisito de URL explícita ni una pausa de seguridad.

## 4. Qué se observa

Cada consulta puede producir una observación por combinación exacta de SKU y
vendedor. Se conserva:

- tienda, URL y producto externo;
- SKU y referencias de producto y SKU;
- título, marca, modelo y categoría;
- variante y condición;
- vendedor e indicador de marketplace;
- moneda, precio total y precio de lista;
- disponibilidad y cantidad disponible cuando es confiable;
- cuotas en un campo separado;
- momento de observación, versión del extractor, hash del payload y flags de
  calidad.

Para Oechsle y Promart el vendedor propio debe identificarse con `sellerId=1` y
la identidad esperada de la tienda. Los demás vendedores permanecen como
marketplace. La moneda admitida para alertas es PEN. Una cuota individual nunca
se convierte en precio total y se almacena en su estructura separada. Tarjeta o
medio de pago, membresía, cupón, cantidad mínima y promoción son condiciones
informativas: se muestran en la CLI y Telegram y deben coincidir entre las dos
observaciones de confirmación mediante su familia y una huella opaca de la
condición exacta.

Continúan bloqueando los problemas de identidad o vendedor, variante, ubicación,
base de precio, moneda, precio o stock, además de los flags desconocidos. Las
referencias históricas y equivalentes generales solo utilizan observaciones
limpias, sin flags de calidad.
La disponibilidad procede del catálogo online público y no garantiza stock de
entrega para un distrito específico de Lima.

## 5. Probar una sola URL

Primero deben pasar las pruebas con fixtures. Oechsle y Promart disponen de
pruebas específicas:

```bash
uv run pytest -q -p no:cacheprovider \
  tests/unit/test_oechsle_parser.py \
  tests/unit/test_promart_parser.py \
  tests/unit/test_store_registry.py
```

Detén primero cualquier proceso `uv run bot-ofertas run` con `Ctrl+C`; de otro
modo podría reclamar productos mientras se prepara la prueba.

La CLI todavía no tiene un filtro `crawl --product`. Para garantizar que una
prueba viva consulte exactamente una URL, esa URL debe ser el único producto
activo y elegible en la base local de desarrollo:

1. Ejecuta `uv run bot-ofertas product list` y guarda los UUID de los demás
   productos activos.
2. Desactiva temporalmente cada uno con
   `uv run bot-ofertas product disable UUID_DEL_PRODUCTO`.
3. Agrega o activa únicamente la URL que se probará.
4. Ejecuta una sola consulta:

```bash
uv run bot-ofertas crawl --force --limit 1
```

5. Revisa el estado, el identificador de corrida y las observaciones:

```bash
uv run bot-ofertas history --limit 20
uv run bot-ofertas analyze --limit 20
uv run bot-ofertas alert list --all --limit 20
```

6. Verifica manualmente moneda, vendedor, SKU, variante, unidad, condición,
   disponibilidad, precio total, precio de lista, cuotas y cualquier promoción
   condicionada.
7. Restaura siempre los productos anteriores, incluso si el rastreo falla, con
   `uv run bot-ofertas product enable UUID_DEL_PRODUCTO`.

No ejecutes el spider directamente para escribir historial: el pipeline exige
un target explícito y un lease válido. Tampoco ejecutes `notify` durante el
*smoke test* salvo que quieras realizar una entrega real por Telegram.

## 6. Operación periódica y resultados

Un ciclo aislado:

```bash
uv run bot-ofertas run --once
```

Monitor continuo:

```bash
uv run bot-ofertas run
```

Resultados operativos:

```bash
uv run bot-ofertas product list
uv run bot-ofertas history --limit 20
uv run bot-ofertas alert list --limit 20
uv run bot-ofertas alert list --all --limit 20
```

`history` muestra vendedor, variante, condición, marketplace, cantidad de
opciones de cuota, condiciones comerciales y advertencias de calidad.
`alert list --all` repite ese contexto y explica tanto las ofertas como los
rechazos por marketplace, moneda, condición, variante u otros controles. Una
alerta sigue siendo un indicio y no garantiza que el precio o el stock continúen
disponibles.

## 7. Detenerse ante bloqueos

El spider se detiene ante HTTP 403, 429 o 503, HTML inesperado de bloqueo o una
señal de CAPTCHA. El circuito pausa toda la tienda durante seis horas, revoca
los leases pendientes y muestra hasta cuándo quedó pausada.

Ante cualquiera de esas señales:

1. Si el monitor continuo sigue abierto, detenlo con `Ctrl+C`.
2. No vuelvas a ejecutar con `--force`; esa opción tampoco evita el circuito.
3. Desactiva los productos de la tienda afectada con sus UUID si se necesita una
   pausa más larga:

```bash
uv run bot-ofertas product disable UUID_DEL_PRODUCTO
```

4. Conserva el estado y el identificador de corrida mostrados en la terminal.
5. Revisa otra vez `robots.txt`, términos, forma de la respuesta, frecuencia y
   `User-Agent`.
6. No cambies de IP, identidad o ruta y no intentes resolver el CAPTCHA.
7. Solo después de entender la causa, actualizar fixtures y aprobar las pruebas,
   realiza otro *smoke test* de una URL. Si el bloqueo se repite, deja la tienda
   deshabilitada y solicita orientación o permiso al sitio.

No edites directamente `store_crawl_states` para acortar la pausa. Una respuesta
normal posterior al vencimiento cerrará el circuito de forma controlada.
