from django.urls import path

from .views import ProofOfLifeCreateView, ProofOfLifeSuccessView

app_name = 'pol'

urlpatterns = [
    path(
        'pol/create/',
        ProofOfLifeCreateView.as_view(),
        name='create'
    ),

    path(
        'pol/success/',
        ProofOfLifeSuccessView.as_view(),
        name='success'
    ),
]
