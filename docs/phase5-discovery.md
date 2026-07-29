# Fase 5.1: descubrimiento controlado

La Fase 5.1 encuentra fichas de producto en las tres tiendas ya revisadas sin
convertir el bot en un crawler universal. El sistema sigue trabajando solo con
Coolbox, Oechsle y Promart, en Perú, y el análisis de precios continúa exigiendo
PEN.

Este documento conserva el alcance original de 5.1. La ampliación posterior a
Cassinelli, EFE y La Curacao se documenta en
[Fase 5.2: nuevas tiendas y beta por Telegram](phase5-2-expansion-beta.md).

## Flujo

```text
Adapter declara sitemap y límites
        ↓
PostgreSQL reclama la fuente con un lease
        ↓
Scrapy obedece robots.txt
        ↓
Consulta índice + un sitemap de productos rotado
        ↓
Normaliza y deduplica URLs /slug/p
        ↓
Candidato queda pendiente
        ↓
Administrador aprueba o rechaza
        ↓
Solo el aprobado entra a tracked_products
        ↓
Los ciclos posteriores consultan precio, detectan y alertan
```

Programar una fuente no la descarga desde la API. La API solo adelanta
`next_run_at`; el worker la atiende en su siguiente ciclo. Esto mantiene la red
fuera del proceso HTTP y permite reinicios, auditoría y escalamiento.

## Límites iniciales

| Tienda | Intervalo | Sitemaps por vuelta | Candidatos | Aprobaciones/día | Activos máximos |
| --- | ---: | ---: | ---: | ---: | ---: |
| Coolbox | 24 h | 2 | 100 | 20 | 500 |
| Oechsle | 24 h | 2 | 75 | 15 | 400 |
| Promart | 24 h | 2 | 75 | 15 | 400 |

Los dos documentos son el índice y un archivo `product-N.xml`. La consulta de
`robots.txt` de Scrapy es adicional y obligatoria. El cursor rota entre los
archivos oficiales, por lo que el catálogo se incorpora progresivamente.

## Estados

Fuentes y corridas:

- `never`, `running`, `succeeded`, `partial`, `failed`, `blocked` o
  `cancelled`.

Candidatos:

- `pending`: espera revisión.
- `approved`: creó un producto monitoreado.
- `rejected`: conserva el motivo de la decisión.
- `duplicate`: la URL ya estaba descubierta o monitoreada.
- `policy_blocked`: reservado para una decisión de política.
- `unavailable`: reservado para una fuente que reporte una baja explícita.

La deduplicación usa la URL canónica y una huella SHA-256 por tienda. Las
aprobaciones se serializan por fuente para que dos administradores no superen
el límite diario o el máximo activo mediante una carrera.

## Panel

En `http://localhost:3000`, abre **Descubrimiento**:

1. Revisa el estado y los límites de cada fuente.
2. Pulsa **Programar** si quieres adelantar una fuente al próximo ciclo.
3. Espera a que el worker termine la ejecución.
4. Filtra candidatos pendientes.
5. Aprueba los útiles o recházalos indicando un motivo.

La aprobación crea un producto activo con el intervalo mínimo seguro de su
adapter. No genera una alerta inmediata: primero debe existir una observación de
precio válida y luego se aplican las mismas reglas de detección, confirmación y
deduplicación de las fases anteriores.

## CLI de diagnóstico

```bash
uv run bot-ofertas discovery sources
uv run bot-ofertas discovery run
uv run bot-ofertas discovery candidates --status pending
uv run bot-ofertas discovery approve UUID
uv run bot-ofertas discovery reject UUID --reason "No priorizado"
```

`discovery run --force` ignora únicamente la fecha programada. Nunca omite
`robots.txt`, el lease, la concurrencia por dominio, el máximo de documentos o
el máximo de candidatos.

## API administrativa

Todas estas rutas requieren el Bearer token local:

- `GET /api/v1/discovery/sources`
- `POST /api/v1/discovery/sources/{id}/run`
- `GET /api/v1/discovery/candidates`
- `POST /api/v1/discovery/candidates/{id}/review`
- `POST /api/v1/discovery/candidates/review`
- `GET /api/v1/discovery/runs`

La revisión en bloque admite como máximo 20 candidatos y es transaccional.

## Seguridad

El parser XML rechaza documentos vacíos, mayores de 12 MiB, DTD, entidades y
raíces que no sean `sitemapindex` o `urlset`. Los hijos deben permanecer en el
hostname HTTPS declarado por el adapter y coincidir con el patrón exacto de
productos. No se siguen redirects durante el descubrimiento.

Ante HTTP 403, 429, 503, HTML inesperado, bloqueo o CAPTCHA, Scrapy detiene la
fuente y el circuito pausa la tienda. No existen proxies rotativos, cambios de
identidad ni resolución de CAPTCHA.

La política viva y sus enlaces oficiales están en
[Política de fuentes](source-policy.md).

## Reinicio

El descubrimiento usa el worker existente; no añade otro contenedor. Después de
actualizar:

```powershell
.\scripts\bot-ofertas.ps1 start
```

El servicio de migraciones aplica `0012_phase5_discovery`. Los candidatos,
cursores, decisiones y corridas permanecen en PostgreSQL al apagar la PC.
