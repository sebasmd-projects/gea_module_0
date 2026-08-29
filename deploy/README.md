# Notas de despliegue

## Archivos de media protegidos

Los PDF de certificacion y los documentos de identidad **no deben servirse
directamente por el servidor web**. Antes lo estaban: cualquiera con la URL
—o que la adivinara— se descargaba incluso el original sin codigos, saltandose
por completo la verificacion OTP.

En el servidor:

```bash
cp deploy/media.htaccess "$DJANGO_MEDIA_ROOT/.htaccess"
```

Comprueba que quedo bien (debe responder 404, no el PDF):

```bash
curl -I https://geausa.propensionesabogados.com/public/media/certificates/documents/certified_<uuid>.pdf
```

La via valida es `certificates:document_file`, que comprueba permisos:

| Archivo | Ruta | Quien |
|---|---|---|
| Original sin codigos | `…/file/source/` | Solo `is_staff` / `is_superuser` |
| Certificado con codigos | `…/file/certified/` | Solo `is_staff` / `is_superuser` |
| Copia distribuible | `…/file/public/` | Sesion OTP valida o autenticado |

**Mejor todavia**: mover `DJANGO_MEDIA_ROOT` fuera del directorio publico
(`public/`). Asi el servidor web no puede servirlo aunque el `.htaccess` se
pierda en un despliegue. Requiere mover los archivos existentes y ajustar la
variable de entorno.

## Estaticos

`ManifestStaticFilesStorage` anade un hash al nombre de cada archivo, asi que
un JS o CSS actualizado deja de quedarse cacheado en el navegador. Obliga a
ejecutar `collectstatic` **antes** de servir:

```bash
uv run python manage.py collectstatic --noinput
```

Si un fichero referenciado desde un CSS no existe, `collectstatic` falla: eso
es intencionado, avisa del enlace roto antes de que llegue a produccion.
