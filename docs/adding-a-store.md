# Cómo añadir una tienda

El núcleo del bot no necesita conocer cada tienda. Una integración se encapsula
en un adapter que declara su identidad, dominios, política y spider. El registro
elige ese adapter a partir de la URL; la CLI y el pipeline trabajan con su
contrato común.

Este diseño reduce el código que hay que cambiar, pero no convierte al bot en un
scraper universal. Una tienda nueva solo debe habilitarse después de revisar su
dominio y probar su extracción.

## Flujo de resolución

```text
URL pública
  -> resolve_store(...) / StoreRegistry.resolve(...)
  -> StoreRegistry.detect(...)
  -> adapter registrado por dominio
  -> normalize_product_url(...)
  -> producto guardado con adapter.slug
  -> adapter.spider_class
  -> PriceObservation
  -> pipeline PostgreSQL común
  -> historial normalizado
  -> DealDetector común
  -> deduplicación persistente
  -> Telegram
```

El registro incorpora:

- adapters incluidos en este repositorio;
- adapters de paquetes externos descubiertos mediante el grupo de entry points
  `bot_ofertas.store_adapters`.

Un dominio desconocido o un adapter deshabilitado se rechaza. El registro tampoco
permite slugs duplicados ni que dos adapters reclamen el mismo hostname. No
existe un adapter comodín que intente consultar cualquier sitio.

## 1. Revisar la fuente antes de programar

Para cada dominio:

1. Revisa `robots.txt` y los términos de uso vigentes.
2. Identifica únicamente fichas y endpoints públicos que no requieran login,
   carrito ni checkout.
3. Define una frecuencia conservadora, concurrencia por dominio y señales de
   detención.
4. Registra la decisión en
   [la política de fuentes](source-policy.md), incluso si la tienda queda
   deshabilitada.
5. No implementes evasión de CAPTCHA, proxies rotativos, suplantación de
   identidad ni mecanismos para eludir bloqueos.

Si aparecen HTTP 403, 429 o 503, HTML de bloqueo o CAPTCHA, el spider debe
detenerse según las protecciones comunes del proyecto.

## 2. Implementar el adapter

El adapter debe cumplir el contrato común de tiendas y concentrar lo específico
del dominio:

- `slug`: identificador estable y único;
- `display_name`: nombre visible;
- `hosts`: hostnames exactos admitidos;
- `policy`: una instancia de `StorePolicy`;
- `spider_class`: la clase Scrapy que obtiene la fuente pública;
- `normalize_product_url(...)`: validación y canonicalización de la URL;
- parser que produce observaciones normalizadas.

`StorePolicy` declara `enabled`, `minimum_interval_minutes`,
`max_targets_per_run`, `requires_explicit_product_url` y notas de la revisión.
Los intervalos menores a 30 minutos y los lotes no positivos se rechazan.

No introduzcas comprobaciones como `if store == "..."` en la CLI, el pipeline o
los repositorios. La nueva integración debe entrar por `StoreRegistry` y exponer
el spider mediante su adapter.

Para conservar las mismas protecciones, el spider de una tienda debe especializar
`BoundedProductSpider`. Esta base limita el lote, exige targets explícitos,
detecta CAPTCHA/bloqueos y detiene la corrida ante HTTP 403, 429 o 503. Para APIs
JSON existe `JsonProductSpider`, que además rechaza HTML inesperado y JSON
inválido. Una tienda cuya fuente pública sea HTML puede extender
`BoundedProductSpider` y aportar su propio `decode_response(...)`. La subclase
siempre aporta la URL pública de consulta y el parser de su payload.

El spider también declara `request_hosts`, la lista exacta de hosts públicos
revisados que puede consultar. La base vuelve a validar cada URL generada por
`build_request_url(...)`: debe ser HTTPS, no contener credenciales y permanecer
en uno de esos hosts, que a su vez debe estar cubierto por `allowed_domains`.

Si la tienda usa una plataforma ya soportada, por ejemplo VTEX, extrae o reutiliza
una base compartida para construir solicitudes y normalizar respuestas. Aun así,
mantén por dominio su política, dominios permitidos, fixtures y casos límite: una
misma plataforma puede tener configuraciones de catálogo, sellers o precios
distintas.

## 3. Registrar la integración

Un adapter que forma parte de este repositorio se agrega a la colección de
adapters integrados.

Un paquete externo se anuncia con el entry point:

```toml
[project.entry-points."bot_ofertas.store_adapters"]
mi_tienda = "mi_paquete.store:MiTiendaAdapter"
```

El entry point puede exportar una instancia de `StoreAdapter`, una subclase
instanciable sin argumentos o una factory sin argumentos que devuelva el
adapter. Tras instalar el paquete en el mismo entorno de Python, verifica que
aparezca:

```bash
uv run bot-ofertas store list
```

Los slugs y dominios deben ser únicos. El registro rechaza duplicados para evitar
que una URL se envíe al extractor equivocado.

## 4. Añadir fixtures y pruebas

Las pruebas de una tienda no deben depender de su sitio en vivo. Guarda payloads
representativos como fixtures, eliminando datos que no sean necesarios, y cubre:

- URL válida, URL no canónica y URL ajena al dominio;
- producto normal y múltiples variantes;
- precio total separado de cuotas;
- precio de lista y descuento;
- múltiples vendedores y marketplace;
- agotados y cantidades centinela;
- accesorios, reacondicionados o caja abierta cuando existan;
- respuestas incompletas, JSON inválido y HTML de bloqueo;
- SKU, vendedor y variante estables en la observación normalizada.

Ejecuta:

```bash
uv run pytest -q -p no:cacheprovider
uv run ruff check .
```

La prueba transaccional de PostgreSQL se incluye con:

```bash
RUN_POSTGRES_TESTS=1 uv run pytest -q -p no:cacheprovider
```

## 5. Habilitarla de forma controlada

1. Mantén el adapter deshabilitado hasta completar la revisión y las pruebas.
2. Comprueba su presencia con `store list`.
3. Registra una sola URL pública de prueba.
4. Ejecuta una consulta controlada y revisa `crawl_runs`,
   `price_observations` y los contadores de error.
5. Verifica que cuotas, variantes, vendedores y condiciones no se mezclen.
6. Aumenta productos y frecuencia gradualmente sin superar los límites de la
   fuente.

Los productos pendientes se reclaman con leases en PostgreSQL y
`FOR UPDATE SKIP LOCKED`. Esto permite añadir workers sin duplicar un producto
durante la vigencia del lease. No elimina los límites por dominio: cada worker
debe conservar la configuración responsable de Scrapy.

El pipeline exige un lease válido y verifica en la misma transacción el producto,
la tienda, la URL y el token antes de persistir. No se admite eludir el scheduler
mediante un spider directo que escriba historial sin lease. Los adapters
habilitados también deben usar `BoundedProductSpider` y exigir URLs explícitas.

Los límites e intervalos se evalúan desde la política vigente, incluso para
productos registrados antes de un cambio. Los fallos reciben backoff exponencial.
Una respuesta 403, 429 o 503, o una señal de CAPTCHA, pausa toda la tienda seis
horas mediante `store_crawl_states`; `--force` no evita ese circuito.

## Qué no resuelve el registro

El registro detecta automáticamente una tienda entre las integraciones
disponibles; no descubre ni comprende cualquier ecommerce de Internet. La
estructura HTML, APIs, variantes, sellers, moneda, precios condicionados a
tarjeta y reglas legales cambian entre sitios. Por eso cada dominio requiere una
integración verificable.

El detector, el scheduler, la deduplicación y Telegram ya forman parte del flujo
común. Al habilitar un adapter compatible, sus observaciones alimentan esos
módulos sin modificar el núcleo. Esto no elimina la revisión específica de
precios condicionados, variantes, vendedores y casos límite de cada tienda.
