# Fase 6.8: canal comercial diversificado

Fecha de implementación: 3 de agosto de 2026.

## Problema observado

El catálogo y el rastreo estaban distribuidos entre quince tiendas, pero una
ola de variantes nuevas de Topitop y Footloose produjo 77 de las 80
publicaciones de las últimas 24 horas. El sistema no estaba inventando ni
duplicando ofertas: moda y calzado tenían más episodios nuevos confirmados que
los demás rubros.

## Corrección

La diversidad se aplica en dos lugares sin descartar ofertas:

1. La cola de Telegram usa las publicaciones de las últimas 24 horas como
   contexto. Cuando existen varias ofertas pendientes, salen primero las
   categorías menos representadas y luego las tiendas dentro de cada rubro.
2. La ampliación del catálogo usa siete días de publicaciones como señal
   adicional. Los nuevos productos compensan primero los rubros que todavía no
   generan suficiente contenido y después las tiendas dentro de esos rubros.

Dentro de cada tienda y categoría se conserva el orden por severidad y
antigüedad. Si solamente existen ofertas válidas de una categoría, se siguen
publicando; el balance nunca fabrica descuentos ni elimina oportunidades.

## Ampliación

El objetivo operativo pasa de 900 a 1 500 productos. La ampliación continúa
usando candidatos descubiertos en sitemaps públicos, revisión segura por
adaptador, deduplicación y límites responsables por tienda.

```powershell
docker compose run --rm worker bot-ofertas discovery expand `
  --target-active 1500 --limit 1000

docker compose run --rm worker bot-ofertas discovery expand `
  --target-active 1500 --limit 1000 --apply
```

Los productos nuevos necesitan ser rastreados y confirmar su precio antes de
generar una publicación. Por ello, la diversidad mejora progresivamente y no
mediante reenvíos artificiales de ofertas antiguas.
