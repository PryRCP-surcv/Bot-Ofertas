# Fase 6.7A: base comercial multicanal

Fecha de implementación: 1 de agosto de 2026.

## Objetivo

Preparar el monitor para operar un canal gratuito y, posteriormente, un canal
VIP sin duplicar el detector, el rastreo ni el historial de precios.

Una oferta se detecta y confirma una sola vez. Después, el enrutador crea una
entrega durable por cada audiencia habilitada:

```text
observación -> detección confirmada -> enrutador
                                      |-> telegram_free
                                      |-> telegram_vip (opcional)
```

Cada entrega tiene lease, reintentos, resultado y auditoría propios. Un fallo
del destino VIP no consume ni elimina la entrega Free, y viceversa.

## Configuración

Las credenciales continúan solamente en `.env`:

```dotenv
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=token_secreto
TELEGRAM_FREE_CHAT_ID=-100...
TELEGRAM_VIP_CHAT_ID=
TELEGRAM_VIP_MIRROR_ENABLED=true
TELEGRAM_OPERATIONS_CHAT_ID=
```

- `TELEGRAM_FREE_CHAT_ID`: canal actual donde llegan las ofertas.
- `TELEGRAM_VIP_CHAT_ID`: canal VIP opcional.
- `TELEGRAM_VIP_MIRROR_ENABLED`: habilita el espejo temporal hacia VIP.
- `TELEGRAM_OPERATIONS_CHAT_ID`: destino privado del watchdog.
- `TELEGRAM_CHAT_ID`: nombre anterior, conservado como fallback de Free.
- `TELEGRAM_ADMIN_CHAT_ID`: nombre anterior, conservado como fallback de
  operaciones.

Si solo existe `TELEGRAM_CHAT_ID`, el comportamiento visible no cambia. El
canal existente sigue recibiendo todas las nuevas ofertas.

No se debe configurar el canal VIP hasta haberlo creado, agregar el bot como
administrador y obtener su identificador. Dejar el valor vacío no bloquea Free.

## Alcance comercial de 6.7A

Durante esta subfase, VIP funciona como espejo opcional. Es una validación de
infraestructura; todavía no hay contenido exclusivo ni retrasos comerciales.
Las reglas que diferencien Free y VIP pertenecen a la Fase 6.7B.

Esto evita lanzar un cobro con una promesa que aún no está automatizada. Primero
se comprueba que ambos destinos reciben de forma independiente y que cualquier
fallo queda visible.

## Auditoría

`notification_deliveries` conserva por cada destino:

- proveedor y audiencia;
- modo de despacho;
- regla y motivo de enrutamiento;
- momento en que se decidió la ruta;
- momento programado para entregar;
- estado, intentos, error y mensaje devuelto por Telegram.

Las entregas históricas del canal `telegram` se migran a `telegram_free`. El
estado resumido de la detección considera todas sus entregas, pero la fuente de
verdad continúa siendo cada fila individual.

## Panel de distribución

La vista **Distribución** muestra:

- si el token y cada audiencia están configurados;
- cola y resultados por destino;
- prueba independiente de Free o VIP;
- porcentaje del catálogo observado en las últimas 24 horas;
- cobertura por tienda;
- reparto de alertas por tienda y categoría;
- advertencia si una sola categoría supera 50 % de las alertas recientes;
- cantidad de productos que siguen clasificados como `Otros`.
- observaciones pendientes de analizar, edad de la más antigua y ciclos
  estimados para recuperar la cola.

La meta de cobertura es 95 % en 24 horas. La advertencia de concentración es
diagnóstica: no descarta ni retiene ofertas.

## Recuperación de la cola de análisis

Al ampliar el catálogo, cada rastreo puede producir más observaciones que el
antiguo lote de análisis. El sistema conserva esas observaciones, pero una
captura histórica no puede publicar como si fuera el precio actual. Para evitar
que ese historial retrase ofertas nuevas:

- el lote predeterminado aumenta a 1 000 observaciones;
- las últimas capturas de productos se analizan antes que el historial;
- la capacidad se configura con `BOT_ANALYSIS_LIMIT` entre 100 y 5 000;
- el panel advierte cuando la cola supera un ciclo o tiene dos horas de edad.

El historial pendiente no se borra: se procesa progresivamente después de la
vía rápida. La confirmación por una segunda consulta, la deduplicación y las
reglas de calidad siguen vigentes.

## Presentación pública de las ofertas

Telegram conserva una publicación comercial breve:

- título normalizado sin repetir la tienda ni códigos internos evidentes;
- tienda, precio vigente, precio anterior o de lista y descuento;
- color, talla y demás variantes con etiquetas legibles;
- condiciones comerciales o de delivery cuando correspondan;
- distintivo `Precio verificado` después de la confirmación;
- imagen y botón directo a la ficha pública.

La confianza numérica, la cantidad exacta de observaciones, las razones del
detector y la referencia interna no se muestran al público. Permanecen
almacenadas en la detección y disponibles para auditoría administrativa.

## Categorías

La taxonomía amplia de 6.6 se mantiene. En 6.7A se reconocen más términos
comerciales de tecnología, electrohogar, belleza, deportes, hogar, moda y
calzado para reducir el grupo `Otros`. El fallback revisado de cada tienda sigue
evitando que una descripción incompleta rompa el balance.

## Puesta en marcha

Antes de aplicar la migración se crea un respaldo verificable de PostgreSQL.
Después:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bot-ofertas.ps1 start
```

El arranque construye las imágenes, aplica `0018_multichannel_delivery` y
reinicia API, worker, watchdog y panel. La compatibilidad con
`TELEGRAM_CHAT_ID` permite hacerlo sin cambiar primero el `.env` actual.

Validaciones recomendadas:

```powershell
.\scripts\bot-ofertas.ps1 status
docker compose logs --tail 100 api worker watchdog
```

En el panel, **Distribución** debe mostrar `Free configurado`. VIP aparecerá
como destino activo solamente cuando tenga un chat ID y el espejo esté
habilitado.

## Límites deliberados

6.7A no incluye:

- pagos automáticos;
- alta o baja automática de miembros;
- contenido distinto entre Free y VIP;
- publicación permanente en un servidor;
- WhatsApp o Gmail.

Esas capacidades se construyen sobre esta base sin volver a rastrear ni
redetectar cada producto por audiencia.
