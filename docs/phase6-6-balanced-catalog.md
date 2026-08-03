# Fase 6.6: catálogo y canal equilibrados

Fecha de implementación: 1 de agosto de 2026.

## Objetivo

Evitar que la cantidad de alertas dependa casi por completo de una sola tienda
o familia de productos, sin ocultar descuentos válidos ni imponer cuotas
comerciales de publicación.

El equilibrio se aplica antes y durante la distribución:

1. el catálogo prioriza tiendas con menor cobertura;
2. dentro de ellas prioriza categorías comerciales subrepresentadas;
3. el rastreo reparte cada vuelta entre los adapters habilitados;
4. una cola con varias alertas intercala tiendas y categorías;
5. todas las alertas pendientes siguen entregándose.

## Categorías amplias

El balance usa una taxonomía deliberadamente pequeña:

- tecnología;
- electrohogar;
- moda;
- calzado;
- hogar y decoración;
- ferretería y mejoramiento;
- supermercado;
- belleza y salud;
- juguetes y bebé;
- deportes y aire libre;
- automotriz;
- otros.

La clasificación utiliza primero la ruta de categoría publicada por la tienda,
después la etiqueta del producto y finalmente el rubro revisado del adapter. No
modifica la clasificación comercial de una oferta ni su porcentaje de
descuento.

## Selección mantenible

`discovery expand` ya no agrega la misma cantidad a cada tienda ignorando su
estado inicial. En cada ejecución vuelve a contar el catálogo activo y elige de
forma determinista:

1. la tienda con menor representación;
2. la categoría menos representada dentro de esa tienda;
3. la categoría menos representada globalmente;
4. el candidato más reciente del grupo elegido.

El objetivo operativo de esta fase es de 900 productos. El algoritmo se vuelve
a ejecutar en cada ampliación futura, por lo que el equilibrio no depende de
una corrección manual única.

Los límites diarios de aprobación usan ahora el día calendario de Lima. Antes
se calculaban desde medianoche UTC, lo que trasladaba el reinicio de cuota a las
19:00 del día anterior en Perú.

## Ropa, calzado y variantes

Topitop y Footloose están autorizadas expresamente para monitorear todos los SKU
exactos devueltos por una ficha revisada:

- cada talla conserva SKU, variante, precio e historial independientes;
- una talla nunca confirma el precio de otra;
- cada SKU requiere dos observaciones separadas por el intervalo configurado;
- si varias tallas disponibles tienen exactamente el mismo vendedor, precio,
  precio de lista, moneda, condición y condiciones comerciales, una sola talla
  representa la notificación;
- Telegram muestra las tallas disponibles agrupadas;
- precios o condiciones diferentes producen grupos independientes.

Las demás tiendas mantienen la regla conservadora anterior: una ficha con
variantes ambiguas exige selección explícita.

## Orden equilibrado de Telegram

Cuando varias ofertas ya confirmadas esperan envío, el sistema toma un lote
mayor, lo intercala por tienda y categoría y después lo entrega. La prioridad
por confianza y severidad se conserva dentro de cada grupo.

Este mecanismo cambia el orden, no la elegibilidad:

- no existe un máximo diario por categoría;
- no se descarta una oferta para favorecer otra;
- los reintentos y leases siguen siendo persistentes;
- una interrupción devuelve las entregas no completadas a la cola al vencer su
  lease.

## Validación

La prueba integral de variantes crea dos tallas de Topitop en dos rastreos
independientes y comprueba que:

- las dos tallas se confirman por separado;
- solo se reserva una entrega;
- la entrega enumera ambas tallas;
- el producto monitoreado no aprende silenciosamente una talla arbitraria.

La aplicación sobre el catálogo real elevó el total de 700 a 900. Después del
rebalanceo, Casaideas, Estilos, Footloose, Metro, plazaVea, Topitop, Tottus,
Vega y Wong quedaron con 52 productos activos cada una. No se añadieron
productos a Cassinelli ni Promart en esta operación.

La primera vuelta desplegada guardó 197 observaciones. Topitop produjo 14
candidatas de moda y Footloose 8 de calzado esperando su segunda comprobación;
ninguna volvió a ser rechazada por `variant_selection_required`. Once tiendas
terminaron sin errores. Tottus terminó parcialmente por ocho payloads públicos
que no cumplieron su contrato estricto; no se relajó el parser ni se abrió su
circuito de bloqueos.

La ampliación debe ejecutarse primero como simulación:

```bash
uv run bot-ofertas discovery expand
```

Y solo después de revisar su distribución:

```bash
uv run bot-ofertas discovery expand --apply
```
