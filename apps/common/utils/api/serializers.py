from rest_framework.serializers import ModelSerializer

from ..models import RequestLogModel


class RequestLogSerializer(ModelSerializer):
    class Meta:
        model = RequestLogModel
        fields = '__all__'
