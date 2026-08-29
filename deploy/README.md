# Notas de despliegue

## Archivos de media protegidos

`MEDIA_ROOT` **vive dentro** del arbol que sirve el servidor web
(`public/media/`), y tiene que seguir asi: las imagenes de activos, las de
ofertas y la galeria se sirven directas, sin pasar por Django. Lo que no puede
servirse directo es lo sensible.

### Requisito previo: que la variable y los archivos coincidan

`FileField` guarda la ruta **relativa** a `MEDIA_ROOT`. Si la variable apunta a
un sitio y los archivos estan en otro, no se pierde nada pero Django deja de
encontrarlos: todo da 404 y las subidas nuevas van al directorio equivocado.
Es un fallo silencioso. Comprobalo con:

```bash
uv run python manage.py check_media
```

### Bloqueo

Dos capas, y conviene poner las dos:

```bash
# 1) En la raiz de MEDIA_ROOT
cp deploy/media.htaccess "$DJANGO_MEDIA_ROOT/.htaccess"

# 2) En cada subarbol sensible (mas robusto: no depende de mod_rewrite)
for d in certificates passport_images signature_images; do
    mkdir -p "$DJANGO_MEDIA_ROOT/$d"
    cp deploy/media-protected.htaccess "$DJANGO_MEDIA_ROOT/$d/.htaccess"
done
```

Comprueba que quedo bien (debe responder 404, no el PDF):

```bash
curl -I https://geausa.propensionesabogados.com/public/media/certificates/documents/certified_<uuid>.pdf
```

### Las vias validas

| Archivo | Ruta | Quien |
|---|---|---|
| Original sin codigos | `certificates:document_file` `…/file/source/` | `is_staff` / `is_superuser` |
| Certificado con codigos | `…/file/certified/` | `is_staff` / `is_superuser` |
| Copia distribuible | `…/file/public/` | Sesion OTP valida o autenticado |
| Foto de empleado | `certificates:employee_photo` | Publica, como la pagina donde aparece |

## Estaticos

`ManifestStaticFilesStorage` anade un hash al nombre de cada archivo, asi que
un JS o CSS actualizado deja de quedarse cacheado en el navegador. Obliga a
ejecutar `collectstatic` **antes** de servir:

```bash
uv run python manage.py collectstatic --noinput
```

Si un fichero referenciado desde un CSS no existe, `collectstatic` falla: eso
es intencionado, avisa del enlace roto antes de que llegue a produccion.
