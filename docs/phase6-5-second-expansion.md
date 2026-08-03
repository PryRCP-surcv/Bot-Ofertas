# Fase 6.5: segunda ampliación de catálogo y cobertura

Fecha de validación: 31 de julio de 2026.

## Resultado

Esta fase amplía el piloto sin eliminar las protecciones que determinan si una
oferta es publicable:

- 700 productos activos en lugar de 500.
- 15 tiendas habilitadas en lugar de 12.
- 90 productos reclamados en una vuelta normal y un máximo manual de 300.
- Una vuelta automática cada cinco minutos, sin solapamiento dentro del worker.
- Hasta 8 fuentes de descubrimiento por vuelta y un máximo manual de 15.
- Confirmación independiente, filtros de calidad, deduplicación y reintentos
  permanecen activos.

Con la configuración normal existen hasta 1.080 espacios de reclamación por
hora. Como el catálogo actual tiene 700 fichas y cada producto respeta su
intervalo mínimo, la demanda real queda limitada aproximadamente a esos 700
productos elegibles por hora. Ninguna de esas cifras significa alertas: una URL
puede producir varias variantes, estar agotada, no cambiar de precio o no
superar los criterios de calidad y descuento.

## Tiendas incorporadas

### Wong

- Fichas HTTPS canónicas terminadas en `/p`.
- Catálogo y sitemap públicos de VTEX.
- Vendedor propio exacto: `sellerId=1` y `WongIO`.
- Moneda PEN y base unitaria fija.
- La alerta recuerda confirmar disponibilidad y delivery para Lima.

### Footloose

- Fichas HTTPS canónicas terminadas en `/p`.
- Catálogo y sitemap públicos de VTEX.
- Vendedor propio exacto: `sellerId=1` e `Inversiones Rubin's SAC`.
- Cada talla se conserva como SKU y variante independiente.

### Casaideas

- Fichas HTTPS canónicas terminadas en `/p`.
- Catálogo y sitemap públicos de VTEX.
- Vendedor propio exacto: `sellerId=1` y `Casaideas Perú`.
- Moneda PEN y base unitaria fija.
- La alerta recuerda confirmar disponibilidad y delivery para Lima.

Cada integración tiene adapter, spider, política, límites y pruebas
independientes aunque las tres reutilicen el parser VTEX común.

## Validación real controlada

Antes de activar productos se comprobó una ficha pública de cada tienda:

| Tienda | Observaciones normalizadas | Resultado |
|---|---:|---|
| Wong | 1 | PEN, vendedor propio, precio y disponibilidad verificados |
| Footloose | 45 | tallas separadas; precio actual y de lista verificados |
| Casaideas | 4 | PEN, vendedor propio, precio/lista y stock verificados |

La primera vuelta operativa posterior produjo resultados correctos para las
tres tiendas. Los fallos puntuales de otras fuentes no abren sus circuitos ni
relajan validadores; quedan registrados para diagnóstico y reintento.

## Ampliación del catálogo

Los candidatos siguieron el flujo normal:

1. descubrimiento desde sitemap oficial;
2. almacenamiento como candidato inactivo;
3. aprobación limitada por tienda;
4. normalización y deduplicación;
5. activación como producto rastreable.

La distribución se mantiene deliberadamente repartida entre las 15 tiendas.
No existe una cuota de alertas por tienda: se publica toda oferta confirmada que
supere la política comercial, pero ninguna tienda puede monopolizar el cupo de
rastreo de una vuelta.

## Recuperación

Antes de ampliar se generó y verificó el respaldo:

```text
backups/postgres/bot-ofertas-pre-phase6-5-20260731.dump
```

Para volver a operar después de apagar la PC:

```powershell
.\scripts\bot-ofertas.ps1 start
.\scripts\bot-ofertas.ps1 status
```

El catálogo, historial, candidatos, alertas y configuración persisten en
PostgreSQL; no se reconstruyen desde cero al reiniciar.
