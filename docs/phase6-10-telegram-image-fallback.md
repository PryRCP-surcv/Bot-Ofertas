# Fase 6.10: respaldo universal de imágenes para Telegram

## Objetivo

Evitar que una tienda o CDN compatible con el catálogo pierda la fotografía en
Telegram cuando el proveedor rechaza que Telegram descargue directamente la URL.
La solución no contiene excepciones por tienda y también cubre dominios que se
incorporen después.

## Flujo de entrega

Para cada oferta con `image_url`:

1. El bot solicita a Telegram `sendPhoto` usando la URL HTTPS original.
2. Si Telegram la acepta, no se descarga nada en el equipo.
3. Si Telegram responde con un error 400 para esa foto, el bot descarga la
   imagen una vez, bajo límites estrictos, y la mantiene únicamente en memoria.
4. El bot vuelve a llamar `sendPhoto`, esta vez como archivo multipart.
5. Si tampoco es una imagen utilizable, la oferta se publica como texto para no
   perder la alerta.

Los errores transitorios de Telegram, como límite 429 o fallo 5xx, no provocan
un mensaje duplicado: la entrega durable conserva su política normal de
reintentos.

## Límites y seguridad

- Solo se aceptan URLs HTTPS públicas, sin credenciales ni puertos alternativos.
- Se rechazan direcciones locales, privadas y no públicas antes de abrir la URL.
- Cada redirección se vuelve a validar.
- El tamaño máximo descargado es 5 MiB.
- Solo se admiten JPEG, PNG y WebP, contrastando cabecera y firma binaria.
- La descarga usa el mismo tiempo máximo acotado del envío a Telegram.
- No se escriben archivos temporales ni se crea una caché persistente.

Esto protege el equipo frente a descargas ilimitadas y evita que una URL de
producto pueda utilizarse para acceder a servicios internos.

## Almacenamiento y auditoría

PostgreSQL sigue almacenando solamente la URL de origen en la observación. Los
bytes descargados dejan de existir al terminar la llamada.

Cada entrega enviada registra uno de estos métodos:

- `photo_url`: Telegram obtuvo la imagen directamente desde la tienda.
- `photo_upload`: el bot la descargó en memoria y la subió.
- `text`: la oferta no tenía imagen.
- `text_fallback`: ambos métodos de foto fallaron y se preservó la alerta.

Esta información permite identificar nuevos CDNs incompatibles sin mostrar
detalles técnicos al público del canal.
