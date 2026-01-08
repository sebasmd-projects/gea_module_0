# GEA

## Dependencias

### Terceros

### Django

### Aplicaciones


## Commands

Descargar la base de datos utf-8
```cmd
python -Xutf8 manage.py dumpdata --natural-foreign --natural-primary --exclude auth.permission --exclude contenttypes --indent 2 --output db_data.json
```