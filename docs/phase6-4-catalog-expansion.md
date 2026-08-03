# Fase 6.4: ampliación de catálogo y cobertura

Fecha de implementación: 31 de julio de 2026.

Esta ampliación eleva la cobertura operativa sin relajar los validadores ni las
pausas de seguridad.

## Capacidad

- Objetivo global: 500 productos activos.
- Rastreo normal: 60 productos por vuelta.
- Máximo aceptado por CLI: 200 productos por vuelta.
- Frecuencia del worker: una vuelta cada 300 segundos.
- Capacidad teórica: 720 posiciones por hora, siempre sujeta a productos
  vencidos, máximos por tienda, `robots.txt`, AutoThrottle y circuitos de salud.
- Descubrimiento: hasta 6 fuentes por vuelta y un máximo técnico de 12.

El sistema no consulta cada producto cada cinco minutos. El repositorio solo
reclama fichas cuyo intervalo venció; las tiendas nuevas conservan 60 minutos
como mínimo y 10 fichas como máximo por tienda dentro de una vuelta.

## Tiendas nuevas

La cobertura pasa de nueve a doce adapters habilitados:

- Estilos: VTEX, vendedor propio y unidad verificados.
- Metro: VTEX, vendedor Cencosud, unidad fija y recordatorio de delivery.
- Tottus: parser propio que contrasta `__NEXT_DATA__` con JSON-LD.

Tai Loy fue evaluada y descartada antes del despliegue porque sus términos
publicados restringen expresamente la reutilización comercial del contenido.
Hiraoka continúa descartada porque su `robots.txt` bloquea Scrapy. No se intenta
evadir ninguna de esas restricciones.

## Activación del catálogo

La simulación no cambia PostgreSQL:

```bash
uv run bot-ofertas discovery expand --target-active 500 --limit 500
```

La aplicación usa únicamente candidatos pendientes de fuentes revisadas:

```bash
uv run bot-ofertas discovery expand --target-active 500 --limit 500 --apply
```

La selección rota entre tiendas, revalida cada URL mediante su adapter, respeta
cuotas técnicas y conserva la aprobación de forma auditable. Los productos de
las tiendas recién incorporadas entran progresivamente después de su primera
vuelta de descubrimiento.

## Verificación

Antes de dejar el worker activo:

1. ejecutar Ruff y todas las pruebas;
2. sincronizar las doce tiendas y sus fuentes;
3. ejecutar migraciones pendientes;
4. realizar un smoke test de una ficha por tienda nueva;
5. aplicar el objetivo de 500 productos;
6. reconstruir y reiniciar API, worker, watchdog y panel;
7. comprobar salud, logs, productos activos, candidatos y observaciones.

La ampliación aumenta las oportunidades analizadas, no garantiza un número de
alertas. Telegram sigue publicando únicamente ofertas confirmadas, válidas y no
duplicadas.
