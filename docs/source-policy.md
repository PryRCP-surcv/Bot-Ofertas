# Política de fuentes

Fecha de revisión inicial: 26 de julio de 2026.

Este proyecto solo consulta recursos públicos. Cada integración debe tener una
revisión independiente de `robots.txt`, términos publicados y comportamiento
técnico antes de habilitarse. Una revisión favorable no equivale a una
autorización contractual y debe repetirse periódicamente.

## Reglas obligatorias

- Usar un `User-Agent` honesto y propio.
- Obedecer `robots.txt` en cada ejecución.
- Consultar únicamente URLs de producto agregadas explícitamente.
- No visitar login, cuenta, carrito, checkout ni endpoints privados.
- Concurrencia máxima de una solicitud por dominio.
- Intervalo mínimo inicial de 30 minutos por producto; recomendado: 60 minutos.
- Pausar la tienda ante HTTP 403, 429, una página de bloqueo o CAPTCHA.
- No usar proxies rotativos, cambios de identidad ni resolución de CAPTCHA.
- Conservar vendedor, SKU, variante, condición y disponibilidad junto al precio.
- Tratar toda alerta como indicio; el bot nunca confirma que una tienda respetará
  un posible error de digitación.

## Estado de tiendas evaluadas

| Tienda | Estado | Motivo |
|---|---|---|
| Coolbox | Piloto habilitado | `robots.txt` permite expresamente `/api/catalog_system/pub/`; las fichas y el catálogo público responden sin login. |
| Oechsle | Candidata para fase 2 | Fichas y catálogo público disponibles; requiere normalizar valores centinela y múltiples variantes. |
| Hiraoka | Deshabilitada | Bloquea explícitamente `User-agent: Scrapy` y sus términos restringen extracción/reutilización. |
| Ripley | Deshabilitada | Las solicitudes HTTP directas reciben un bloqueo 403; no se intentará evadirlo. |

## Coolbox: alcance del piloto

- Dominio permitido: `www.coolbox.pe`.
- Entrada aceptada: una ficha HTTPS cuya ruta termine en `/p`.
- Fuente primaria: catálogo público VTEX permitido por `robots.txt`.
- Vendedor propio esperado: `sellerId=1`; otros vendedores se marcan como
  marketplace y nunca se mezclan con la oferta propia.
- El precio total proviene de `commertialOffer.Price`.
- Las cuotas se almacenan separadas y jamás se interpretan como precio total.
- Cada combinación SKU + vendedor produce una observación independiente.
- Una oferta agotada conserva la disponibilidad, pero no usa precios centinela
  para detectar descuentos.

Recursos públicos revisados:

- <https://www.coolbox.pe/robots.txt>
- <https://www.coolbox.pe/terminos-y-condiciones>
- <https://www.coolbox.pe/sitemap.xml>

## Revisión antes de producción

Antes de desplegar fuera del equipo local se debe:

1. Añadir un medio de contacto válido al `User-Agent`.
2. Confirmar por escrito la frecuencia y el alcance cuando la tienda ofrezca un
   canal para integraciones o feeds.
3. Revalidar términos, `robots.txt` y endpoints.
4. Definir una cuota por dominio y alarmas de bloqueo.
5. Documentar fecha, responsable y evidencia de cada revisión.
