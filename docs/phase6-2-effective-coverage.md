# Fase 6.2: cobertura efectiva y nueve tiendas

Fecha de implementación: 30 de julio de 2026.

Esta ampliación persigue más ofertas útiles, no solo más URLs. El sistema pasa
de seis a nueve adapters habilitados e incorpora plazaVea, Topitop y Vega sin
relajar los filtros comunes de seguridad.

## Resultado

- Nueve tiendas registradas y nueve fuentes de descubrimiento:
  Coolbox, Oechsle, Promart, Cassinelli, EFE, La Curacao, plazaVea, Topitop y
  Vega.
- Primer lote operativo de 171 productos activos.
- Veinte candidatos aprobados por cada tienda nueva, además de una ficha piloto
  validada en vivo.
- Treinta candidatos adicionales de plazaVea y Topitop, y veintinueve de Vega,
  permanecen pendientes. No se rastrean hasta otra aprobación.
- Cuarenta y dos fichas de Oechsle sin stock propio actual fueron desactivadas.
  Su historial no se eliminó y pueden reactivarse desde el panel.
- Promart puede alertar cuando confirma precio online, vendedor propio, unidad
  fija, PEN, variante y stock. Telegram muestra que se debe verificar delivery
  para el distrito de Lima.

## Cómo se añadieron las tres tiendas

Cada integración declara:

1. dominios HTTPS permitidos;
2. normalización estricta de una ficha raíz `/slug/p`;
3. endpoint público de catálogo correspondiente al slug exacto;
4. identidad conjunta de `sellerId` y razón social;
5. límites por corrida e intervalo mínimo;
6. sitemap oficial de descubrimiento;
7. parser, spider, fixture y pruebas propios.

Las tres reutilizan un núcleo VTEX revisado, pero no comparten ciegamente la
identidad del vendedor ni la política comercial.

### plazaVea

- Vendedor propio: `sellerId=1` y `Plaza Vea`.
- Máximo: 5 productos por corrida y 60 minutos por producto.
- Solo una base unitaria con multiplicador uno puede alertar.
- Peso variable, marketplace e identidad ambigua se guardan, pero bloquean la
  alerta.
- Delivery para Lima queda como condición informativa visible.

### Topitop

- Vendedor propio: `sellerId=1` y `TRADING FASHION LINE S.A.`.
- Máximo: 10 productos por corrida y 60 minutos por producto.
- Cada talla se persiste como SKU y variante independiente.
- Un descuento de una talla no se mezcla con otra talla.

### Vega

- Vendedor propio: `sellerId=1` y `CORPORACIÓN VEGA`.
- Máximo: 5 productos por corrida y 60 minutos por producto.
- Solo unidad fija con multiplicador uno puede alertar.
- Delivery para Lima queda como condición informativa visible.

## Validación viva controlada

Scrapy consultó una sola ficha piloto por dominio, obedeció `robots.txt` y
obtuvo:

| Tienda | Observaciones | Moneda | Vendedor propio | Stock |
|---|---:|---|---|---|
| plazaVea | 1 | PEN | Sí | Disponible |
| Topitop | 4 tallas | PEN | Sí | Disponible |
| Vega | 1 | PEN | Sí | Disponible |

No se inició sesión, no se visitó carrito o checkout y no se realizó ninguna
compra.

## Selección efectiva de Oechsle

El diagnóstico del catálogo anterior encontró 43 fichas activas:

- 1 con stock actual del vendedor Oechsle;
- 42 con oferta propia agotada y stock disponible únicamente en marketplace.

Las 42 fichas inefectivas fueron desactivadas para que no consuman el cupo
horario. La observación histórica, candidatos y detecciones permanecen en
PostgreSQL. El descubrimiento seguirá rotando el sitemap y permitirá aprobar
nuevas fichas; antes de mantenerlas en el catálogo debe confirmarse que tengan
stock propio.

## Límites de ampliación

- Descubrimiento: una vuelta por fuente cada 1.440 minutos.
- Documentos: como máximo el índice y un sitemap de productos por vuelta.
- Nuevas tiendas: hasta 50 candidatos descubiertos por vuelta.
- Aprobación: hasta 40 candidatos diarios por tienda.
- Catálogo: máximo inicial de 300 productos activos por cada tienda nueva.
- Rastreo: presupuesto global repartido de forma rotativa entre tiendas, además
  del máximo propio de cada adapter.

La aprobación no garantiza una alerta. Cada ficha debe superar dos
observaciones independientes y todos los validadores del detector.

## Operación

El panel muestra las nueve tiendas, productos activos e inactivos, candidatos y
rastreos. Para continuar ampliando:

1. revisar los candidatos pendientes;
2. aprobar lotes pequeños por tienda;
3. esperar al menos una vuelta completa;
4. medir éxito, stock propio, bloqueos y falsos positivos;
5. desactivar fichas sin cobertura efectiva y reemplazarlas.

La política y las fuentes revisadas están en
[Política de fuentes](source-policy.md).
