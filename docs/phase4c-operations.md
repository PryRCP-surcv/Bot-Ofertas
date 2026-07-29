# Fase 4C: operación local económica

Esta fase ejecuta Bot Ofertas como siete servicios de Docker:

| Servicio | Función | Exposición |
|---|---|---|
| `postgres` | Base de datos e historial | Solo `127.0.0.1` |
| `migrations` | Actualiza el esquema y termina | Ninguna |
| `api` | API administrativa | Solo `127.0.0.1` |
| `worker` | Rastreo, detección y Telegram | Ninguna |
| `watchdog` | Vigila el latido del trabajador | Ninguna |
| `backup` | Respaldo diario con retención | Ninguna |
| `dashboard` | Panel administrativo | Solo `127.0.0.1` |

Los servicios persistentes usan `restart: unless-stopped`. Si Docker Desktop se
reinicia después de un corte o reinicio de Windows, vuelve a iniciarlos. Para que
esto ocurra al iniciar sesión, activa en Docker Desktop:

`Settings > General > Start Docker Desktop when you sign in`.

No se publica ningún puerto en la red local ni en Internet. El panel sigue siendo
una herramienta privada para el administrador y no necesita dominio ni HTTPS en
esta etapa.

## Preparación inicial

1. Inicia Docker Desktop y espera a que muestre `Engine running`.
2. Conserva el archivo `.env` en la raíz del proyecto.
3. Comprueba que `.env` contiene contraseñas reales y:

   - `POSTGRES_DB`
   - `POSTGRES_USER`
   - `POSTGRES_PASSWORD`
   - `BOT_API_ADMIN_TOKEN`
   - las credenciales de Telegram si está habilitado

`.env` está ignorado por Git y por Docker Build. Los secretos se entregan a los
contenedores en tiempo de ejecución y no se copian dentro de las imágenes.

## Encender todo

Desde PowerShell, en la raíz del proyecto:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bot-ofertas.ps1 start
```

La primera ejecución descarga imágenes, instala dependencias y puede tardar
varios minutos. Las siguientes reutilizan la caché de Docker.

El comando realiza estas acciones:

1. inicia PostgreSQL;
2. espera a que la base de datos esté saludable;
3. aplica las migraciones pendientes;
4. inicia la API y comprueba `/health/ready`;
5. inicia el trabajador continuo;
6. inicia un vigilante independiente del trabajador;
7. crea un primer respaldo y programa los siguientes;
8. construye e inicia el panel;
9. comprueba que todos los procesos queden activos.

Después abre:

- Panel: <http://localhost:3000>
- Swagger de la API: <http://127.0.0.1:8000/docs>
- Estado de la API: <http://127.0.0.1:8000/health/ready>

En la pantalla de conexión del panel usa:

- API: `http://127.0.0.1:8000`
- token: el valor de `BOT_API_ADMIN_TOKEN`, no el token de Telegram

No hace falta mantener PowerShell abierto. Docker conserva los procesos en
segundo plano.

## Estado, logs, reinicio y apagado

Estado de todos los servicios:

```powershell
.\scripts\bot-ofertas.ps1 status
```

Logs recientes:

```powershell
.\scripts\bot-ofertas.ps1 logs
```

Logs continuos del trabajador:

```powershell
.\scripts\bot-ofertas.ps1 logs worker -Follow
```

Logs de otro servicio:

```powershell
.\scripts\bot-ofertas.ps1 logs api
.\scripts\bot-ofertas.ps1 logs dashboard
.\scripts\bot-ofertas.ps1 logs postgres
.\scripts\bot-ofertas.ps1 logs backup
.\scripts\bot-ofertas.ps1 logs watchdog
```

Los logs se rotan automáticamente: cada servicio conserva como máximo cinco
archivos de 10 MB. Así se evita llenar el disco con registros antiguos.

## Vigilancia del trabajador

`watchdog` consulta el latido persistente del trabajador sin depender de él. Si
el latido supera el margen permitido, registra un incidente y envía un aviso
administrativo por Telegram; cuando el trabajador se recupera, envía un segundo
aviso. Las incidencias se deduplican para no repetir mensajes en cada consulta.

Configuración predeterminada:

```dotenv
BOT_WATCHDOG_POLL_SECONDS=60
BOT_WATCHDOG_GRACE_SECONDS=180
TELEGRAM_ADMIN_CHAT_ID=
```

`TELEGRAM_ADMIN_CHAT_ID` es opcional. Si está vacío, se utiliza
`TELEGRAM_CHAT_ID`. Para separar alertas internas de las ofertas comerciales,
configura más adelante un chat privado administrativo distinto.

El vigilante puede detectar la caída del proceso `worker`, pero no puede avisar
si toda la PC pierde energía, Internet o Docker. Esa supervisión externa
corresponde a una etapa de despliegue permanente.

Reiniciar el conjunto:

```powershell
.\scripts\bot-ofertas.ps1 restart
```

Detenerlo:

```powershell
.\scripts\bot-ofertas.ps1 stop
```

`stop` no borra el volumen de PostgreSQL. No uses `docker compose down -v`,
porque `-v` elimina el historial persistente.

El contenedor `migrations` debe aparecer como `Exited (0)` o `exited` después del
arranque. Es normal: su única tarea es actualizar la base de datos y terminar.

## Copias de seguridad

El servicio `backup` crea un respaldo al arrancar y luego uno cada 24 horas.
Conserva 14 días de forma predeterminada. Los valores se pueden ajustar en
`.env`:

```dotenv
BOT_BACKUP_INTERVAL_SECONDS=86400
BOT_BACKUP_RETENTION_DAYS=14
```

Los respaldos automáticos usan el mismo formato y la misma carpeta segura que
el script manual. Para comprobar la última ejecución:

```powershell
.\scripts\bot-ofertas.ps1 logs backup
```

Crear y validar un respaldo:

```powershell
.\scripts\backup-postgres.ps1
```

Los archivos se guardan de forma predeterminada en:

```text
backups\postgres\bot-ofertas-AAAAMMDD-HHMMSS.dump
```

El script:

1. ejecuta `pg_dump` en formato personalizado;
2. verifica el archivo con `pg_restore --list`;
3. lo copia al equipo;
4. elimina únicamente respaldos `bot-ofertas-*.dump` vencidos dentro de la
   carpeta seleccionada.

La retención predeterminada es de 14 días. Se puede cambiar:

```powershell
.\scripts\backup-postgres.ps1 -RetentionDays 30
```

También se puede elegir una carpeta explícita:

```powershell
.\scripts\backup-postgres.ps1 `
  -Destination "D:\Respaldos\BotOfertas" `
  -RetentionDays 30
```

El borrado de retención no es recursivo, rechaza la raíz de una unidad y nunca
elimina archivos que no coincidan con el nombre de respaldo del proyecto.

Para una protección real, copia periódicamente al menos un respaldo a otra
unidad o almacenamiento externo. Un respaldo guardado únicamente en la misma
PC no protege frente a una falla total del disco.

## Comprobación de un respaldo sin sobrescribir producción

Antes de necesitar una recuperación real, conviene probar un respaldo en una
base temporal. Este procedimiento no modifica `bot_ofertas`:

```powershell
$backup = "C:\ruta\bot-ofertas-AAAAMMDD-HHMMSS.dump"
$postgres = (docker compose ps -q postgres).Trim()

docker cp $backup "${postgres}:/tmp/restore-test.dump"
docker exec $postgres sh -ec 'dropdb --if-exists -U "$POSTGRES_USER" bot_ofertas_restore_test'
docker exec $postgres sh -ec 'createdb -U "$POSTGRES_USER" bot_ofertas_restore_test'
docker exec $postgres sh -ec 'pg_restore -U "$POSTGRES_USER" -d bot_ofertas_restore_test /tmp/restore-test.dump'
docker exec $postgres sh -ec 'psql -U "$POSTGRES_USER" -d bot_ofertas_restore_test -c "\dt"'
```

La sustitución de la base productiva es una operación destructiva y debe
realizarse solamente con el bot detenido, un respaldo adicional y una revisión
explícita del archivo que se restaurará.

## Qué ocurre al pulsar “Rastrear productos”

El trabajador `worker` permanece activo y consulta la cola administrativa en
cada ciclo. El panel puede crear un trabajo de rastreo, pero se siguen respetando:

- el límite por tienda;
- el máximo de productos del trabajo;
- las pausas ante bloqueo o CAPTCHA;
- el intervalo mínimo cuando el trabajo no solicita una ejecución forzada.

Los trabajos no descubren productos nuevos. El descubrimiento de catálogos
corresponde a la Fase 5.

## Solución rápida de problemas

### El navegador dice `ERR_CONNECTION_REFUSED`

```powershell
.\scripts\bot-ofertas.ps1 status
.\scripts\bot-ofertas.ps1 logs api
.\scripts\bot-ofertas.ps1 logs dashboard
```

Si los servicios están detenidos:

```powershell
.\scripts\bot-ofertas.ps1 start
```

### La API está saludable pero el rastreo no avanza

```powershell
.\scripts\bot-ofertas.ps1 logs worker -Follow
```

Comprueba que `worker` esté `running` y revisa si la tienda está cumpliendo una
pausa o si el producto aún no venció su intervalo.

### Se modificó código o dependencias

Ejecuta de nuevo:

```powershell
.\scripts\bot-ofertas.ps1 start
```

El comando reconstruye las imágenes y aplica las migraciones antes de levantar
la nueva versión.

### Se modificó únicamente `.env`

Docker Compose debe recrear los contenedores para recibir las variables nuevas:

```powershell
docker compose up -d --force-recreate
```

## Límites actuales

- La disponibilidad depende de que la PC y Docker Desktop estén encendidos.
- El administrador sigue siendo único.
- No existe aún una supervisión externa capaz de avisar si toda la PC pierde
  energía o Internet.
- Los pagos, clientes y membresías pertenecen a la Fase 6A.
- El panel y la API no deben publicarse mediante reenvío de puertos.
