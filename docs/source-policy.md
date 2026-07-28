# Política de fuentes

Última revisión: 28 de julio de 2026.

Este proyecto solo consulta recursos públicos para observar precios; no inicia
sesión, no agrega productos al carrito y no realiza compras. Cada dominio
requiere una revisión independiente de `robots.txt`, términos publicados,
fuentes técnicas y casos límite antes de habilitarse.

Esta política es una decisión técnica conservadora, no una opinión legal.
Que `robots.txt` no bloquee una ruta no equivale a una autorización contractual.
Las fuentes deben revalidarse antes de cada piloto y periódicamente mientras la
integración permanezca activa.

## Reglas obligatorias

- Usar un `User-Agent` honesto, propio y con un contacto válido antes de
  desplegar fuera del equipo local.
- Obedecer `robots.txt` en cada ejecución.
- Consultar únicamente URLs HTTPS de producto agregadas explícitamente.
- No usar categorías, búsquedas ni sitemaps para descubrimiento durante estos
  pilotos; los sitemaps citados abajo son evidencia pública, no una cola de
  rastreo.
- No visitar login, cuenta, carrito, checkout ni endpoints privados.
- Mantener una sola solicitud concurrente por dominio, pausas conservadoras y
  `AutoThrottle`.
- Detener la tienda ante HTTP 403, 429 o 503, una página de bloqueo o CAPTCHA.
- No usar proxies rotativos, cambios de identidad ni resolución de CAPTCHA.
- Conservar SKU, vendedor, variante, condición, disponibilidad, moneda, precio
  total y precio de lista.
- Guardar las cuotas en su estructura separada. Una cuota individual nunca
  sustituye al precio total del producto.
- Marcar tarjeta o medio de pago, membresía, cupón, cantidad mínima y promoción
  como condiciones informativas. Pueden generar una alerta, pero deben mostrarse
  claramente y coincidir, mediante una huella exacta y opaca, entre las dos
  observaciones de confirmación.
- Mantener limpias las referencias históricas y equivalentes generales: solo
  observaciones sin flags de calidad forman esas referencias.
- Bloquear problemas de identidad, vendedor, variante, ubicación, base de
  precio, moneda, precio o stock, además de cualquier flag desconocido.
- Tratar cada combinación SKU + vendedor como una oferta independiente. Un
  vendedor tercero se marca como marketplace y no se mezcla con la tienda.
- Las alertas son indicios. Ninguna alerta garantiza stock, disponibilidad,
  precio final ni que la tienda respetará un posible error de digitación.

## Estado de tiendas evaluadas

| Tienda | Estado al 2026-07-28 | Evidencia y decisión |
|---|---|---|
| Coolbox | Piloto habilitado | Su [`robots.txt`](https://www.coolbox.pe/robots.txt) permite expresamente `/api/catalog_system/pub/`; las fichas y el catálogo público VTEX responden sin login. Sus [términos](https://www.coolbox.pe/terminos-y-condiciones) contemplan marketplace, condiciones por medio de pago y errores tipográficos. El [sitemap](https://www.coolbox.pe/sitemap.xml) solo se registró como evidencia. |
| Oechsle | Piloto habilitado | Su [`robots.txt`](https://www.oechsle.pe/robots.txt) bloquea checkout y publica un [sitemap](https://www.oechsle.pe/sitemap.xml), sin bloquear las fichas `/p` ni el catálogo público usado por el adapter. Sus [términos](https://www.oechsle.pe/terminos-y-condiciones) advierten variaciones de precio, marketplace y promociones o cuotas con Tarjeta Oh!. Las pruebas y un rastreo vivo controlado de una ficha pasaron el 28 de julio de 2026. |
| Promart | Piloto de historial habilitado; alertas bloqueadas | Su [`robots.txt`](https://www.promart.pe/robots.txt) bloquea checkout y publica un [sitemap](https://www.promart.pe/sitemap.xml); fichas y catálogo público VTEX respondieron sin login en la revisión. Sus [términos](https://www.promart.pe/terminos-y-condiciones) indican precios según ciudad de despacho, marketplace y posible anulación por error de digitación. Las pruebas y un rastreo vivo controlado de una ficha pasaron el 28 de julio de 2026. Toda observación conserva `location_context_unverified`, por lo que el detector no alerta hasta modelar una ubicación comprobable. |
| plazaVea | Diferida | Aunque su [`robots.txt`](https://www.plazavea.com.pe/robots.txt) publica un [sitemap](https://www.plazavea.com.pe/sitemap.xml) y existe un catálogo público, sus [términos](https://www.plazavea.com.pe/terminos-y-condiciones) incluyen productos por peso, ubicación, marketplace, sustituciones y reacondicionados. Se difiere hasta modelar correctamente esas dimensiones. |
| Hiraoka | No integrar | Su [`robots.txt`](https://hiraoka.com.pe/robots.txt) bloquea expresamente `User-agent: Scrapy`; además, sus [términos](https://hiraoka.com.pe/terminos-y-condiciones) restringen la extracción y reutilización del sitio. |
| Ripley | No integrar | La consulta directa incluso de su [`robots.txt`](https://simple.ripley.com.pe/robots.txt) recibió una página de bloqueo del perímetro. Sus [términos oficiales](https://simple.ripley.com.pe/minisitios/especial/servicio-al-cliente/terminos-condiciones/index.html) también describen Mercado Ripley y precios variables. No se intentará evadir el bloqueo. |
| Tai Loy | No integrar | Su [`robots.txt`](https://www.tailoy.com.pe/robots.txt) solo declara agentes concretos y publica un sitemap; no ofrece una autorización general. Sus [términos](https://www.tailoy.com.pe/terminos-y-condiciones) restringen reproducción, puesta a disposición y reutilización sin autorización escrita. |
| Memory Kings | No integrar | Su [`robots.txt`](https://www.memorykings.pe/robots.txt) bloquea expresamente varios agentes de IA y no se localizó una página oficial de términos generales de uso entre los enlaces públicos revisados. La [política de datos](https://www.memorykings.pe/ley-proteccion-datos) no sustituye esa autorización. No se integrará sin aclaración escrita. |

## Alcance de Coolbox

- Dominios admitidos: `coolbox.pe` y `www.coolbox.pe`.
- Entrada aceptada: ficha HTTPS cuya ruta termine en `/p`.
- Fuente primaria: catálogo público VTEX permitido expresamente por
  `robots.txt`.
- Vendedor propio esperado: `sellerId=1`; los demás vendedores se conservan
  como marketplace y quedan fuera de alertas.
- El precio total proviene de `commertialOffer.Price`.
- Las cuotas se almacenan por separado.
- Los agotados conservan su disponibilidad, pero sus precios no se usan para
  detectar descuentos.
- La política vigente en código permite un mínimo de 30 minutos y hasta 20 URLs
  por corrida. Operativamente se recomienda comenzar con 60 minutos y lotes
  pequeños.

## Alcance operativo de Oechsle y Promart

Los dos pilotos deben cumplir todas estas condiciones:

1. Aceptar únicamente fichas explícitas HTTPS terminadas en `/p`.
2. Aplicar un intervalo mínimo de 60 minutos y un máximo de 5 URLs por corrida.
3. Trabajar en PEN sobre el catálogo online público. Este piloto no confirma
   stock de entrega para un distrito concreto de Lima; cualquier disponibilidad
   local debe verificarse en la ficha antes de actuar sobre una alerta.
4. Reconocer como vendedor propio únicamente `sellerId=1` junto con la identidad
   esperada de la tienda. Cualquier inconsistencia se marca como ambigua.
5. Guardar vendedores marketplace y cuotas por separado; marcar las condiciones
   comerciales como informativas, mostrarlas en la alerta y exigir la misma
   familia en ambas observaciones de confirmación.
6. Verificar SKU, variante, unidad de venta, condición, disponibilidad, precio
   total y precio de lista mediante fixtures.
7. Repetir las pruebas automatizadas y un *smoke test* de una sola URL ante
   cambios sustanciales de fuente o parser.
8. Añadir productos gradualmente y revisar la evidencia antes de ampliar el
   lote.

En Promart el parser solo considera verificable una base con
`measurementUnit` de unidad y `unitMultiplier=1`. Cualquier campo ausente o base
por peso, superficie, longitud o multiplicador distinto genera
`unsupported_price_basis`. Además, todas sus observaciones reciben
`location_context_unverified`: se guardan en el historial, pero el detector las
rechaza hasta incorporar un contexto geográfico verificable.

## Motivos para diferir plazaVea

La fuente pública es técnicamente similar a VTEX, pero una misma comparación
puede cambiar por:

- peso final y unidad de venta;
- ubicación y disponibilidad;
- sustituciones de supermercado;
- vendedores marketplace o internacionales;
- condición nueva, reacondicionada o reconstruida;
- promociones ligadas al medio de pago.

Aunque `phase3-v2` ya muestra las condiciones comerciales, integrar plazaVea
antes de representar correctamente peso, sustituciones, ubicación, vendedor y
condición produciría falsos positivos. La decisión se revisará cuando todas esas
dimensiones puedan verificarse de forma equivalente.

## Revisión antes de ampliar o desplegar

1. Revalidar los enlaces oficiales y guardar la fecha de revisión.
2. Confirmar que la ficha y la fuente pública sigan teniendo la forma probada.
3. Ejecutar fixtures y pruebas unitarias sin depender del sitio vivo.
4. Ejecutar un único *smoke test* con los límites de
   [operación de la Fase 2](phase2-operations.md).
5. Revisar vendedor, moneda, cuota, condiciones comerciales mostradas, variante,
   condición, disponibilidad y flags bloqueantes.
6. Añadir un contacto válido al `User-Agent` antes de operar permanentemente.
7. Solicitar confirmación escrita cuando exista un canal para feeds o
   integraciones.
