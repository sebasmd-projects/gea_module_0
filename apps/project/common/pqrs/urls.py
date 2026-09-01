# apps/project/common/pqrs/urls.py
from django.urls import path

from .views import PQRSReceiptView, PQRSWizardView

app_name = 'pqrs'

urlpatterns = [
    path(
        'pqrs/',
        PQRSWizardView.as_view(),
        name='new'
    ),
    # El radicado va en la URL, asi que esta pagina no puede enseñar datos
    # personales: un radicado circula por correo y por captura de pantalla.
    path(
        'pqrs/radicado/<str:radicado>/',
        PQRSReceiptView.as_view(),
        name='receipt'
    ),
]
