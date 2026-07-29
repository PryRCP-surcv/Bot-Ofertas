# Panel administrativo de Bot Ofertas

Frontend de la Fase 4B para administrar la API local de Bot Ofertas. Está
construido con React, TypeScript, vinext y CSS responsive.

## Seguridad

- El panel solicita `BOT_API_ADMIN_TOKEN` al abrirse.
- El token se conserva únicamente en memoria dentro de `ApiClient`.
- No se usa `localStorage`, `sessionStorage`, cookies ni variables públicas de
  compilación.
- Al recargar o cerrar la pestaña se debe introducir el token nuevamente.
- Un `401` o `403` borra la credencial y vuelve a la pantalla de conexión.

El frontend no debe publicarse conectado directamente a una API HTTP local. La
Fase 4C lo ejecuta únicamente en `localhost` como herramienta privada del
administrador. Un despliegue permanente requiere HTTPS, autenticación
multiusuario y una política de acceso; eso corresponde a fases futuras.

## Operación recomendada

Solo se necesita Docker Desktop activo y el `.env` configurado en la raíz del
proyecto. Desde PowerShell:

```powershell
cd C:\Users\TU_USUARIO\Documents\Proyectos\bot-ofertas
.\scripts\bot-ofertas.ps1 start
```

El mismo comando deja activos PostgreSQL, API, worker, watchdog, respaldo y
panel, y aplica las migraciones. No hace falta mantener terminales abiertas.

Abre `http://localhost:3000`. Introduce:

- API: `http://127.0.0.1:8000`
- Token: el valor real de `BOT_API_ADMIN_TOKEN` guardado en el `.env` de la raíz

La API y el panel solo escuchan en `localhost`. Los futuros clientes reciben
alertas por Telegram y no acceden al panel. La disponibilidad depende de que la
PC, Docker Desktop e Internet permanezcan activos.

La guía de estado, reinicio, logs y respaldos está en
[Fase 4C: operación local económica](../docs/phase4c-operations.md).

## Desarrollo del frontend

Para modificar el panel fuera de Docker se requiere Node.js `>=22.13.0`, la API
disponible en `http://127.0.0.1:8000` y CORS habilitado para
`http://localhost:3000`.

Desde Windows PowerShell:

```powershell
cd C:\Users\TU_USUARIO\Documents\Proyectos\bot-ofertas\dashboard
npm install
$env:npm_config_script_shell='C:\Program Files\Git\bin\bash.exe'
npm run dev
```

Esta modalidad es solo para desarrollo. En la operación normal, Docker ejecuta
la API y el worker en segundo plano. Si el worker está apagado, los trabajos
pueden quedar en cola aunque el panel y la API estén disponibles.

## Validación

```powershell
npm run lint
npm run typecheck
npm test
```

`npm test` construye la aplicación, renderiza la entrada segura y verifica que
la credencial no se persista.

## Pantallas

- **Resumen:** ofertas recientes, confirmaciones, productos por tienda, salud de
  API y estado real del worker.
- **Ofertas:** activas, por confirmar e historial con filtros y evidencia.
- **Productos:** alta, edición, activación, historial y archivado lógico.
- **Tiendas:** estado y límites de cada adapter, en modo lectura.
- **Rastreo:** elegibilidad, selección de productos, confirmación antes de
  encolar, cancelación, corridas Scrapy, heartbeat y último ciclo del worker.
- **Configuración:** política versionada con ETag, idempotencia y motivo de
  cambio.

El botón del resumen abre la pantalla de rastreo; no consulta tiendas
inmediatamente. En **Rastreo**, el administrador revisa los productos elegibles,
prepara la solicitud y la confirma antes de enviarla a la cola. El worker sigue
respetando intervalos, cuotas y pausas de seguridad.
