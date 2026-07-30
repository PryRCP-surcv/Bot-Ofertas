# Fase 6.1: beta comercial controlada

La Fase 6.1 convierte el canal privado de Telegram en una beta que se puede
administrar sin contratar todavía una pasarela de pago. El bot continúa
enviando ofertas a un único grupo o canal y el administrador mantiene el
control de quién entra, quién debe renovar y quién debe salir.

## Alcance

- Registrar nombre, usuario de Telegram y datos de contacto opcionales.
- Distinguir prueba, activo, vencido y suspendido.
- Registrar si la persona está pendiente, dentro o retirada del grupo.
- Guardar inicio, vencimiento y días restantes.
- Confirmar pagos externos en PEN y renovar la vigencia.
- Consultar el historial de pagos por suscriptor.
- Mostrar vencimientos durante los siguientes siete días.
- Mostrar ingresos confirmados del mes y acumulados.
- Mostrar entregas de Telegram durante 7 y 30 días.
- Mantener una lista persistente de preparación del lanzamiento.

No se almacenan números de tarjeta, claves, códigos bancarios ni credenciales
de Yape o Plin. El pago debe confirmarse primero fuera del sistema. El panel
solo registra el monto, método, referencia opcional, fecha y cobertura.

## Flujo recomendado

```text
Persona interesada
  -> registrar suscriptor en prueba
  -> agregar manualmente al grupo privado
  -> marcar "Dentro del grupo"
  -> confirmar pago por el medio acordado
  -> registrar pago en el panel
  -> la vigencia se extiende de forma atómica
  -> revisar próximos vencimientos
  -> renovar o retirar manualmente de Telegram
```

Un pago comienza su cobertura al terminar la vigencia actual. Si la persona ya
venció, comienza desde el momento del registro. Registrar un pago reactiva al
suscriptor y, si estaba retirado, deja su acceso pendiente para recordar que
debe volver a añadirse manualmente.

Cada pago exige `Idempotency-Key`. Repetir exactamente la misma solicitud
devuelve el mismo registro y no renueva dos veces. Reutilizar la clave con otro
monto o cobertura devuelve un conflicto.

## Pantalla Suscriptores

Abre `http://localhost:3000`, conecta la API y selecciona **Suscriptores**.

La pantalla incluye:

- resumen de vigentes, vencimientos, ingresos y accesos pendientes;
- buscador y filtro por estado;
- alta inicial con prueba de 3, 7, 15 o 30 días;
- administración del estado comercial y del acceso a Telegram;
- confirmación de pago y renovación de 7 a 90 días;
- historial de pagos;
- advertencia comercial visible;
- lista de preparación de la beta.

Cambiar el estado de acceso en el panel no agrega ni retira a nadie de
Telegram. Primero realiza la acción en el grupo y después registra el resultado
para mantener ambos estados alineados.

## API administrativa

Todas estas rutas requieren el bearer administrativo:

```text
GET   /api/v1/commercial/summary
GET   /api/v1/commercial/checklist
PUT   /api/v1/commercial/checklist/{item_key}
GET   /api/v1/subscribers
POST  /api/v1/subscribers
GET   /api/v1/subscribers/{subscriber_id}
PATCH /api/v1/subscribers/{subscriber_id}
GET   /api/v1/subscribers/{subscriber_id}/payments
POST  /api/v1/subscribers/{subscriber_id}/payments
```

Las actualizaciones de suscriptores requieren `If-Match` con la versión actual.
Esto evita sobrescribir un cambio realizado desde otra pestaña. Los pagos son
registros confirmados e inmutables durante esta beta.

## Lista de lanzamiento

Los controles obligatorios son:

1. aprobar el catálogo inicial;
2. validar una alerta real en Telegram;
3. configurar el grupo privado;
4. publicar las reglas;
5. publicar la advertencia sobre precios y stock;
6. comprobar una recuperación de respaldo;
7. completar una prueba continua de 24 horas.

Invitar al grupo piloto es opcional en el cálculo de preparación. El indicador
`launch_ready` exige completar todos los controles obligatorios y tener
Telegram configurado.

## Advertencia sugerida para el grupo

> Bot Ofertas informa precios públicos detectados automáticamente. El precio,
> stock, vendedor y condiciones finales pertenecen a cada tienda y pueden
> cambiar, agotarse o ser cancelados. Verifica siempre la ficha antes de pagar.

El servicio no compra productos, no representa a las tiendas y no garantiza
que un posible error de precio sea respetado.

## Persistencia y privacidad

PostgreSQL conserva suscriptores, pagos y lista de lanzamiento. El dashboard no
usa almacenamiento del navegador como fuente de verdad. El token
administrativo permanece únicamente en memoria y los clientes no acceden al
panel.

La instalación local sigue dependiendo de que la PC, Docker Desktop e Internet
permanezcan activos. El funcionamiento permanente en un servidor corresponde
a la siguiente fase.

## Migración y pruebas

La migración `0014_phase6_1_commercial_beta` crea:

- `beta_subscribers`;
- `beta_payments`;
- `beta_launch_checklist_items`.

Validación recomendada:

```bash
uv run ruff check .
uv run pytest tests/unit -q -p no:cacheprovider
RUN_POSTGRES_TESTS=1 uv run pytest tests/integration -q -p no:cacheprovider
```

Para el dashboard:

```powershell
npm run lint
npm run typecheck
npm test
```
