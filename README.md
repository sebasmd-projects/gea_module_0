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

## Iniciar proyecto con uv

```cmd
uv init
uv venv
.venv\Scripts\activate
uv add -r requirements.txt
uv run python manage.py runserver
```

## Añadir paquetes
```cmd
uv add <paquete>
```

## Instalar paquetes
```cmd
uv lock --upgrade
uv sync
```


## Exportar requirements

```cmd
uv export --format=requirements-txt > requirements.txt
```

## Activar tunel

```powershell
cd C:\Users\USUARIO\.ssh
ssh -p 1022 -i "$env:USERPROFILE\.ssh\ssh_access" -L 3307:127.0.0.1:3306 propensi@190.90.160.103
```

Mantener la terminal abierta

