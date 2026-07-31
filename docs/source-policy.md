# Política de fuentes

Última revisión: 30 de julio de 2026.

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
- Para observar precios, consultar únicamente fichas HTTPS que ya estén en
  `tracked_products`.
- Para descubrir candidatos, usar solo fuentes declaradas por el adapter y
  revisadas en esta política. En Fase 5.2 se admiten exclusivamente los
  sitemaps oficiales de Coolbox, Oechsle, Promart, Cassinelli, EFE,
  La Curacao, plazaVea, Topitop y Vega.
- No usar búsquedas ni categorías. Cada ejecución de descubrimiento consulta
  como máximo el índice, `robots.txt` cuando corresponda y un sitemap de
  productos rotado; nunca recorre todos los archivos de una tienda a la vez.
- Mantener los candidatos inactivos hasta aprobación administrativa. Descubrir
  una URL no consulta su precio ni la incorpora automáticamente al monitoreo.
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
- Bloquear problemas de identidad, vendedor, variante, ubicación ambigua, base
  de precio, moneda, precio o stock, además de cualquier flag desconocido. Una
  ubicación de delivery que la persona deba confirmar puede mostrarse como
  condición informativa únicamente cuando el precio online, vendedor y unidad
  ya fueron verificados.
- Tratar cada combinación SKU + vendedor como una oferta independiente. Un
  vendedor tercero se marca como marketplace y no se mezcla con la tienda.
- Las alertas son indicios. Ninguna alerta garantiza stock, disponibilidad,
  precio final ni que la tienda respetará un posible error de digitación.

## Estado de tiendas evaluadas

| Tienda | Estado al 2026-07-30 | Evidencia y decisión |
|---|---|---|
| Coolbox | Piloto y descubrimiento habilitados | Su [`robots.txt`](https://www.coolbox.pe/robots.txt) permite expresamente `/api/catalog_system/pub/` y anuncia el [sitemap](https://www.coolbox.pe/sitemap.xml). Las fichas y el catálogo público VTEX responden sin login. Sus [términos](https://www.coolbox.pe/terminos-y-condiciones) contemplan marketplace, condiciones por medio de pago y errores tipográficos. |
| Oechsle | Piloto y descubrimiento habilitados | Su [`robots.txt`](https://www.oechsle.pe/robots.txt) bloquea checkout y publica un [sitemap](https://www.oechsle.pe/sitemap.xml), sin bloquear las fichas `/p` ni el catálogo público usado por el adapter. Sus [términos](https://www.oechsle.pe/terminos-y-condiciones) advierten variaciones de precio, marketplace y promociones o cuotas con Tarjeta Oh!. Las pruebas, un rastreo vivo controlado de una ficha y la primera vuelta acotada de descubrimiento pasaron entre el 28 y 29 de julio de 2026. |
| Promart | Piloto y descubrimiento habilitados | Su [`robots.txt`](https://www.promart.pe/robots.txt) bloquea checkout y publica un [sitemap](https://www.promart.pe/sitemap.xml); fichas y catálogo público VTEX respondieron sin login en la revisión. Sus [términos](https://www.promart.pe/terminos-y-condiciones) indican precios según ciudad de despacho, marketplace y posible anulación por error de digitación. Desde el 30 de julio el parser exige vendedor Promart, unidad fija y coincidencia exacta de ficha, y muestra `delivery_location_confirmation` como recordatorio informativo. Marketplace, unidad variable e identidad ambigua siguen bloqueados. |
| Cassinelli | Piloto y descubrimiento habilitados | Su [`robots.txt`](https://www.cassinelli.com/robots.txt) separa rutas privadas de las fichas públicas. El [índice público revisado](https://www.cassinelli.com/sitemap.xml), las fichas y el catálogo VTEX respondieron sin login. Sus [términos](https://www.cassinelli.com/terminos-y-condiciones) describen venta web en Perú y precios en soles. Las bases variables por peso, superficie o longitud se guardan, pero bloquean alertas hasta representar la unidad exacta. |
| EFE | Piloto y descubrimiento habilitados | Su [`robots.txt`](https://www.efe.com.pe/robots.txt) bloquea búsqueda, cuenta y checkout, y anuncia el [sitemap oficial](https://www.efe.com.pe/media/sitemap/sitemap_efe.xml). La ficha pública expone Product/Offer JSON-LD en PEN y precio HTML verificable. Sus [términos](https://www.efe.com.pe/terminos-y-condiciones) contemplan marketplace y señalan la ficha como referencia final. |
| La Curacao | Piloto y descubrimiento habilitados | Su [`robots.txt`](https://www.lacuracao.pe/robots.txt) bloquea búsqueda, cuenta y checkout, y anuncia el [sitemap oficial](https://www.lacuracao.pe/media/sitemap/sitemap_curacao.xml). La ficha pública expone Product/Offer JSON-LD en PEN y precio HTML verificable. Sus [términos](https://www.lacuracao.pe/terminos-y-condiciones) contemplan marketplace y venta online en Perú. |
| plazaVea | Piloto de unidad fija y descubrimiento habilitados | Su [`robots.txt`](https://www.plazavea.com.pe/robots.txt) publica el [sitemap oficial](https://www.plazavea.com.pe/sitemap.xml) y separa rutas privadas del catálogo público. Sus [términos](https://www.plazavea.com.pe/terminos-y-condiciones) contemplan ubicación, productos por peso y marketplace. El adapter solo considera elegible `sellerId=1` junto con `Plaza Vea`, `measurementUnit` unitaria y `unitMultiplier=1`; el resto se conserva, pero bloquea la alerta. El smoke test del 30 de julio guardó una ficha pública en PEN y stock propio. |
| Topitop | Piloto y descubrimiento habilitados | Su [`robots.txt`](https://www.topitop.pe/robots.txt) publica el [sitemap oficial](https://www.topitop.pe/sitemap.xml) y excluye cuenta y checkout. La [tienda pública](https://www.topitop.pe/) expone catálogo VTEX con SKU por talla. El adapter exige `sellerId=1` junto con `TRADING FASHION LINE S.A.` y conserva cada talla como variante separada. El smoke test del 30 de julio guardó cuatro tallas en PEN y stock propio. |
| Vega | Piloto de unidad fija y descubrimiento habilitados | Su [`robots.txt`](https://www.vega.pe/robots.txt) publica el [sitemap oficial](https://www.vega.pe/sitemap.xml) y excluye cuenta, login, búsqueda y checkout. Sus [términos](https://www.vega.pe/terminos-y-condiciones-generales) cubren la venta online. El adapter exige `sellerId=1` junto con `CORPORACIÓN VEGA`, unidad fija y confirmación visible de delivery. El smoke test del 30 de julio guardó una ficha pública en PEN y stock propio. |
| Tottus | Diferida | Su [`robots.txt`](https://www.tottus.com.pe/robots.txt) distingue fichas y rutas privadas, pero el sitemap revisado respondió de forma inestable y el catálogo depende de ubicación. No se fuerza la integración ni se intenta eludir esa indisponibilidad. |
| Hiraoka | No integrar | Su [`robots.txt`](https://hiraoka.com.pe/robots.txt) bloquea expresamente `User-agent: Scrapy`; además, sus [términos](https://hiraoka.com.pe/terminos-y-condiciones) restringen la extracción y reutilización del sitio. |
| Ripley | No integrar | La consulta directa incluso de su [`robots.txt`](https://simple.ripley.com.pe/robots.txt) recibió una página de bloqueo del perímetro. Sus [términos oficiales](https://simple.ripley.com.pe/minisitios/especial/servicio-al-cliente/terminos-condiciones/index.html) también describen Mercado Ripley y precios variables. No se intentará evadir el bloqueo. |
| Tai Loy | No integrar | Su [`robots.txt`](https://www.tailoy.com.pe/robots.txt) solo declara agentes concretos y publica un sitemap; no ofrece una autorización general. Sus [términos](https://www.tailoy.com.pe/terminos-y-condiciones) restringen reproducción, puesta a disposición y reutilización sin autorización escrita. |
| Memory Kings | No integrar | Su [`robots.txt`](https://www.memorykings.pe/robots.txt) bloquea expresamente varios agentes de IA y no se localizó una página oficial de términos generales de uso entre los enlaces públicos revisados. La [política de datos](https://www.memorykings.pe/ley-proteccion-datos) no sustituye esa autorización. No se integrará sin aclaración escrita. |

## Descubrimiento controlado de Fases 5.1 y 5.2

- Fuentes activas: los nueve índices oficiales ya citados.
- Frecuencia mínima: una vuelta por fuente cada 1.440 minutos.
- Presupuesto por vuelta: dos documentos de sitemap como máximo, además de la
  comprobación de `robots.txt` realizada por Scrapy.
- Rotación: el índice selecciona un único archivo cuyo path coincida
  exactamente con `/sitemap/product-N.xml`; el cursor persistente continúa con
  otro archivo en la siguiente vuelta.
- Volumen: hasta 100 candidatos en Coolbox y 75 en Oechsle o Promart por
  ejecución; Cassinelli, EFE, La Curacao, plazaVea, Topitop y Vega incorporan
  hasta 50 por ejecución. Un candidato repetido se actualiza, no se duplica.
- Activación: manual desde el panel o la API, con 40 aprobaciones diarias por
  tienda. Los máximos activos iniciales siguen siendo 500 para Coolbox, 400
  para Oechsle o Promart y 300 para Cassinelli, EFE, La Curacao, plazaVea,
  Topitop o Vega.
- Seguridad: solo HTTPS, mismo hostname revisado, sin credenciales, puertos
  alternativos, redirects externos, DTD ni entidades XML. Un 403, 429, 503,
  bloqueo o CAPTCHA pausa la tienda y no se intenta evadirlo.
- Promart, plazaVea y Vega conservan `delivery_location_confirmation`: no
  bloquea una oferta válida, pero obliga a que Telegram recuerde confirmar
  disponibilidad y delivery para el distrito de Lima.
- Los sitemaps Magento de EFE y La Curacao mezclan categorías y productos. El
  parser solo toma entradas que incluyen la extensión estándar `image:image`;
  después el adapter vuelve a exigir una ficha raíz `.html` exacta.

## Alcance de las tiendas incorporadas en Fase 5.2

- Cassinelli acepta exclusivamente fichas `/slug/p` y usa su endpoint público
  VTEX. Opera con un intervalo mínimo de 60 minutos, hasta 10 productos por
  corrida, 50 candidatos por descubrimiento y 40 aprobaciones diarias.
- EFE y La Curacao aceptan únicamente fichas raíz `producto.html`. Cada página
  debe contener exactamente un Product y un Offer JSON-LD que correspondan a
  la URL solicitada.
- El precio actual de EFE y La Curacao proviene del Offer JSON-LD y debe
  concordar con `data-price-type="finalPrice"` del HTML. El precio de lista se
  toma de `oldPrice`; una discrepancia bloquea la alerta.
- Las tres integraciones conservan moneda, stock, SKU y vendedor. EFE y La
  Curacao reconocen al vendedor propio por nombre; los demás quedan marcados
  como marketplace.
- Los smoke tests del 29 de julio de 2026 verificaron una ficha pública en PEN
  para cada una de las tres tiendas, sin iniciar sesión ni visitar carrito o
  checkout.

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
`unsupported_price_basis`. Una oferta propia válida recibe
`delivery_location_confirmation`: puede alertar, pero el mensaje recuerda
comprobar delivery y disponibilidad para el distrito de Lima. Una identidad de
vendedor inconsistente sigue generando un flag bloqueante.

## Alcance de plazaVea, Topitop y Vega

Las tres tiendas comparten el parser VTEX, pero conservan adapters, identidad de
vendedor, dominio, spider, límites, fixtures y pruebas independientes:

- plazaVea y Vega solo permiten bases unitarias exactas. Kilogramos,
  multiplicadores distintos de uno y campos ausentes generan
  `unsupported_price_basis` y no pueden alertar.
- plazaVea reconoce como vendedor propio únicamente la combinación revisada
  `sellerId=1` y `Plaza Vea`; Vega exige `sellerId=1` y
  `CORPORACIÓN VEGA`.
- Topitop exige `sellerId=1` y `TRADING FASHION LINE S.A.`. Cada talla queda
  separada por SKU y variante, por lo que no se mezclan tallas al comparar.
- Los vendedores terceros se guardan como marketplace, pero el detector los
  excluye. Un ID propio con nombre no revisado, o viceversa, genera un flag de
  identidad ambiguo bloqueante.
- El payload debe corresponder exactamente al slug solicitado. No se acepta que
  una respuesta de búsqueda distinta sustituya silenciosamente a la ficha.
- Todos operan en PEN, con una solicitud concurrente por dominio, pausa,
  `robots.txt`, `AutoThrottle` y circuito ante 403, 429, 503, bloqueo o CAPTCHA.

El alta del 30 de julio comenzó con 20 candidatos aprobados por tienda, más una
ficha piloto validada en vivo. Los demás candidatos permanecen pendientes para
otra ampliación y no consumen rastreos.

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
