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

El frontend no debe publicarse conectado directamente a una API HTTP local. Un
despliegue permanente requiere primero publicar el backend con HTTPS,
autenticación multiusuario y una política de acceso adecuada; ese cierre
corresponde a la Fase 4C.

## Requisitos

- Node.js `>=22.13.0`.
- API de Bot Ofertas disponible en `http://127.0.0.1:8000`.
- PostgreSQL, migraciones y adapters listos.
- CORS de la API con `http://127.0.0.1:3000` y
  `http://localhost:3000`.

## Desarrollo local

Desde Windows PowerShell:

```powershell
cd C:\Users\TU_USUARIO\Documents\Proyectos\bot-ofertas\dashboard
npm install
$env:npm_config_script_shell='C:\Program Files\Git\bin\bash.exe'
npm run dev
```

Abre `http://localhost:3000`. Introduce:

- API: `http://127.0.0.1:8000`
- Token: el valor real de `BOT_API_ADMIN_TOKEN` guardado en el `.env` de la raíz

La API y `bot-ofertas run` se ejecutan en terminales separadas. Si el monitor
está apagado, los trabajos pueden quedar en cola aunque el panel y la API estén
disponibles.

## Validación

```powershell
npm run lint
npm run typecheck
npm test
```

`npm test` construye la aplicación, renderiza la entrada segura y verifica que
la credencial no se persista.

## Pantallas

- **Resumen:** ofertas recientes, confirmaciones, productos por tienda y salud.
- **Ofertas:** activas, por confirmar e historial con filtros y evidencia.
- **Productos:** alta, edición, activación, historial y archivado lógico.
- **Tiendas:** estado y límites de cada adapter, en modo lectura.
- **Rastreo:** selección de productos, cola, cancelación y corridas Scrapy.
- **Configuración:** política versionada con ETag, idempotencia y motivo de
  cambio.
