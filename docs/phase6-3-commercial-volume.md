# Fase 6.3: volumen comercial con calidad

Fecha de implementación: 31 de julio de 2026.

Esta fase aumenta la cantidad de oportunidades útiles sin convertir el canal en
una lista de precios sin validar. No existe un máximo comercial de alertas por
tienda ni por día: toda oferta que supere la política, la segunda comprobación,
los validadores y la deduplicación entra en la cola durable de Telegram.

## Clasificación

| Reducción | Clasificación pública | Evidencia exigida |
|---|---|---|
| 20–34,99 % | Buena oferta | Historial, precio anterior o equivalentes suficientes |
| 35–49,99 % | Oferta imperdible | Evidencia normal o dos lecturas estables frente al precio de lista |
| 50–69,99 % | Oferta excepcional | La misma validación, con prioridad alta de entrega |
| 70 % o más | Posible error de precio | Dos familias independientes de referencias y confianza suficiente |

Un descuento de 70 % basado únicamente en el precio de lista se publica como
oferta excepcional, no como posible error. Así se comunica la oportunidad sin
atribuir a la tienda un error que el sistema todavía no puede demostrar.

Los precios con tarjeta, cupón, membresía o cantidad mínima siguen siendo
elegibles y Telegram muestra la condición. Continúan bloqueados:

- una cuota confundida con el precio total;
- vendedor marketplace o ambiguo donde se exige vendedor propio;
- variante distinta o no seleccionada;
- moneda distinta de PEN;
- accesorio que no coincide con el producto configurado;
- unidad, peso o base comercial incompatible con el adapter.

## Publicación sin topes comerciales

La publicación no usa una cuota por tienda ni una cuota diaria. Las únicas
compuertas son de calidad:

1. observación válida;
2. descuento suficiente;
3. confirmación independiente cuando corresponde;
4. confianza o precio de lista verificado desde el umbral configurable;
5. episodio no duplicado.

La cola es durable. Las detecciones con mayor severidad se reclaman primero,
pero las ofertas normales permanecen pendientes y se envían en las siguientes
entregas. Un error temporal o un `retry_after` de Telegram provoca reintento; no
descarta la alerta.

## Imagen del producto

Los adapters VTEX y Magento extraen la imagen pública del SKU o producto y la
guardan en cada nueva observación como una URL HTTPS validada. Cuando la
observación que confirma una oferta contiene imagen, Telegram publica:

- la foto del producto;
- la explicación resumida de la oferta como descripción;
- un botón **Ver producto** que abre la ficha pública.

Si Telegram no puede descargar o decodificar la foto y responde con una
solicitud inválida, el emisor vuelve automáticamente al mensaje completo de
texto. Los límites temporales y fallos de red conservan el reintento normal, por
lo que no se intenta un segundo envío que pueda duplicar la alerta.

Las observaciones anteriores a la migración conservan `image_url` vacío. No se
reescribe el historial: las imágenes aparecerán progresivamente conforme cada
producto sea rastreado de nuevo.

El umbral especial se configura con:

```dotenv
BOT_VERIFIED_LIST_PRICE_ALERT_PERCENT=35
```

También aparece en **Configuración** del panel como
**Precio de lista verificado desde (%)** y cada modificación crea una revisión
auditable.

## Capacidad de rastreo

El worker mantiene vueltas cada 300 segundos. La Fase 6.4 elevó la configuración
predeterminada de 40 a 60 productos por vuelta y el máximo de CLI de 100 a 200.
Con 60 productos por vuelta existe una capacidad teórica de 720 posiciones por
hora.
Cada adapter conserva su propio máximo por corrida, intervalo mínimo,
`robots.txt`, pausas ante bloqueos y circuito de salud.

Esta capacidad no significa consultar una ficha 12 veces por hora. El
repositorio solo reclama productos cuyo intervalo venció y distribuye el cupo
de forma rotativa entre tiendas.

## Ampliación controlada del catálogo

La meta de esta fase fue aproximarse a 300 productos activos. La Fase 6.4 elevó
el objetivo a 500. El comando primero simula un plan equilibrado entre tiendas:

```bash
uv run bot-ofertas discovery expand --target-active 500 --limit 500
```

Para aplicarlo:

```bash
uv run bot-ofertas discovery expand --target-active 500 --limit 500 --apply
```

La operación:

- utiliza únicamente candidatos descubiertos en fuentes públicas revisadas;
- rota entre tiendas para evitar que una sola consuma todo el lote;
- conserva la validación de dominio y URL del adapter;
- respeta la cuota técnica de altas y el máximo de catálogo de cada fuente;
- deja en PostgreSQL quién aprobó cada candidato;
- no modifica ni elimina el historial existente.

La cuota de altas no es una cuota de ofertas. Una vez que una ficha está activa,
puede originar todas las alertas válidas que correspondan.

## Verificación

Después de desplegar:

1. revisar en el panel la política 20/35/70 y el umbral verificado de 35 %;
2. confirmar que worker, API y watchdog estén saludables;
3. simular y aplicar la expansión;
4. esperar dos vueltas completas antes de evaluar el volumen;
5. revisar cola, reintentos, duplicados y distribución por tienda;
6. desactivar fichas persistentemente agotadas o marketplace y reemplazarlas.

La Fase 6.3 no automatiza pagos ni acceso al canal. El alta comercial continúa
siendo manual durante la beta y el administrador conserva el control de la
audiencia.
