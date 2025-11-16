"""
WSGI config for app_core project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os
import logging

from django.core.wsgi import get_wsgi_application

logger = logging.getLogger("startup")
logger.warning("WSGI cold start: cargando aplicación Django (PID=%s)", os.getpid())

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app_core.settings')

application = get_wsgi_application()

logger.warning("WSGI application creada correctamente (PID=%s)", os.getpid())