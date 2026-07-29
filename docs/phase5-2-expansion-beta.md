# Fase 5.2: nuevas tiendas y beta por Telegram

La Fase 5.2 amplía el monitor de tres a seis tiendas y prepara el primer canal
comercial económico. Sigue siendo una operación local y privada: el
administrador usa el panel, mientras los suscriptores reciben alertas en un
único grupo o canal de Telegram.

## Tiendas incorporadas

| Tienda | Fuente de precio | Límite por corrida | Descubrimiento |
| --- | --- | ---: | --- |
| Cassinelli | Catálogo público VTEX | 10 | 50 candidatos/día |
| EFE | Product/Offer JSON-LD + contraste HTML | 5 | 50 candidatos/día |
| La Curacao | Product/Offer JSON-LD + contraste HTML | 5 | 50 candidatos/día |

Cada fuente se ejecuta como máximo una vez cada 24 horas, consulta el índice y
un solo sitemap rotado, y admite 10 aprobaciones diarias con un máximo inicial
de 300 productos activos. Estas cuotas son por tienda: añadir adapters no hace
que una tienda consuma el presupuesto de otra.

EFE y La Curacao publican sitemaps mixtos. Solo se consideran entradas con
`image:image`, y luego la URL debe superar el normalizador estricto
`producto.html`. Cassinelli conserva el formato VTEX `/slug/p`. El documento
XML sigue limitado a 12 MiB y 50.000 ubicaciones, aunque la corrida solo
materializa 50 candidatos.

## Validación de precios

- Solo se acepta moneda ISO; el piloto espera `PEN`.
- Se conserva el vendedor exacto y se marca cualquier marketplace.
- Agotados no aportan precio a la detección.
- En Magento, el precio JSON-LD debe coincidir con el precio final visible.
- El precio anterior visible se guarda como precio de lista.
- Una URL, Product u Offer ambiguos detienen esa observación.
- Cassinelli guarda productos vendidos por medida, pero
  `variable_measure_price_basis` bloquea la alerta hasta modelar la unidad.

## Beta comercial económica

La distribución usa el `TELEGRAM_CHAT_ID` existente como una sola audiencia:

```text
Oferta confirmada
        ↓
notification_deliveries guarda la entrega
        ↓
Worker reclama con lease y reintentos
        ↓
Bot publica en el grupo/canal configurado
        ↓
Todos los miembros reciben la misma alerta
```

El panel añade **Distribución**, donde se puede:

- confirmar si Telegram está habilitado y completamente configurado;
- ver entregas enviadas, pendientes, en reintento o fallidas;
- consultar el último envío y el último error sanitizado;
- enviar un mensaje de prueba fijo al destino configurado.

El panel nunca devuelve el token ni el chat ID. El mensaje de prueba no acepta
texto del usuario, por lo que no convierte la API en un relay arbitrario.

## Administración de miembros en esta beta

1. El administrador confirma el pago por un medio externo.
2. Agrega o invita manualmente a la persona al grupo privado.
3. Retira manualmente el acceso cuando corresponda.
4. El bot distribuye automáticamente las ofertas confirmadas.

Esta etapa no procesa pagos, no mantiene una tabla de clientes y no entrega
acceso al panel. Es una decisión intencional para validar el servicio con bajo
costo. Cuando el volumen lo justifique se podrá añadir membresía individual,
vencimientos, pagos y audiencias segmentadas sin cambiar el detector ni los
adaptadores de tienda.

## API administrativa

Las rutas requieren el Bearer token local:

- `GET /api/v1/distribution/telegram`
- `POST /api/v1/distribution/telegram/test`

La segunda ruta realiza una llamada externa real a Telegram y debe usarse solo
cuando se quiera comprobar el destino.

## Actualización

Desde PowerShell en la raíz:

```powershell
.\scripts\bot-ofertas.ps1 start
```

El servicio `migrations` aplica `0013_phase5_2_store_expansion`; luego se
reconstruyen API, worker y panel. Los servicios continúan escuchando solo en
`localhost`.
