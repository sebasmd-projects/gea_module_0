from rest_framework.generics import DestroyAPIView, ListAPIView
from rest_framework.permissions import IsAdminUser

from ..models import RequestLogModel
from .serializers import RequestLogSerializer


class RequestLogListView(ListAPIView):
    permission_classes = [IsAdminUser]
    queryset = RequestLogModel.objects.all()
    serializer_class = RequestLogSerializer


class RequestLogDestroyAPIView(DestroyAPIView):
    permission_classes = [IsAdminUser]
    queryset = RequestLogModel.objects.all()
    serializer_class = RequestLogSerializer
