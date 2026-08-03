# Fase 6.9: Falabella Perú

Fecha de implementación: 3 de agosto de 2026.

## Alcance

Falabella se incorpora como la tienda número dieciséis mediante un adapter,
spider y parser propios. El bot solo consulta fichas HTTPS públicas y exactas
incluidas en el catálogo monitoreado. El descubrimiento usa exclusivamente el
índice PDP que Falabella publica en `robots.txt`; no recorre búsquedas, cuenta,
carrito ni checkout.

## Validaciones antes de una alerta

Cada observación debe demostrar simultáneamente:

- producto y variante iguales a los identificadores de la URL;
- una única oferta activa para ese SKU;
- moneda `PEN`;
- precio y disponibilidad consistentes entre `__NEXT_DATA__` y Product/Offer
  JSON-LD;
- vendedor directo con `sellerId=FALABELLA_PERU` y nombre `FALABELLA`;
- imagen HTTPS, categoría y condición cuando la ficha las publica.

Los vendedores Marketplace se guardan como evidencia para auditoría, pero el
detector no puede publicar sus precios. Una discrepancia entre vendedor,
producto, variante, moneda, precio o disponibilidad bloquea la alerta.

El precio CMR, cupón, membresía, cantidad o promoción no se descarta. Se
conserva mediante una condición informativa y debe coincidir en las dos
observaciones que confirman la oferta.

## Límites iniciales

- intervalo mínimo por producto: 60 minutos;
- máximo por vuelta de Falabella: 10 fichas;
- descubrimiento: índice y un solo sitemap PDP rotado por ejecución;
- candidatos por descubrimiento: hasta 100;
- aprobaciones diarias iniciales: 20;
- máximo técnico inicial: 300 productos activos.

Estos límites permiten observar bloqueos, cambios de estructura y proporción de
Marketplace antes de aumentar la cobertura. No son una cuota comercial: toda
oferta válida y confirmada puede publicarse.

El catálogo piloto comenzó con 20 fichas de venta directa: cinco de tecnología,
cinco de electrohogar, cinco de belleza y cinco de juguetes. Esta composición
evita que la tienda nueva refuerce la concentración previa en moda o calzado.

## Comprobaciones

Las pruebas unitarias cubren URL y SKU exactos, precio normal y CMR, vendedor
directo, Marketplace, identidad ambigua, moneda distinta de PEN, variante
incorrecta y agotados. El smoke test vivo del 3 de agosto de 2026 verificó una
ficha pública de venta directa con precio, stock e imagen, sin iniciar sesión ni
realizar una compra.
