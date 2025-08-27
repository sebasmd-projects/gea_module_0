from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param


class DefaultPaginationSerializer(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'

    def get_paginated_response(self, data):
        url = self.request.build_absolute_uri()
        total_pages = self.page.paginator.num_pages
        first_page = replace_query_param(
            url, self.page_query_param, 1
        )
        last_page = replace_query_param(
            url, self.page_query_param, total_pages
        )

        return Response({
            'current_page': self.page.number,
            'total_pages': total_pages,
            'page_count': len(data),
            'total_count': self.page.paginator.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'first_page': first_page,
            'last_page': last_page,
            'results': data
        })


class TokenObtainPairResponseSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    user_name = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    is_active = serializers.BooleanField()
    access = serializers.CharField()
    refresh = serializers.CharField()

    def create(self, validated_data):
        raise NotImplementedError()

    def update(self, instance, validated_data):
        raise NotImplementedError()


class TokenRefreshResponseSerializer(serializers.Serializer):
    access = serializers.CharField()

    def create(self, validated_data):
        raise NotImplementedError()

    def update(self, instance, validated_data):
        raise NotImplementedError()


class TokenVerifyResponseSerializer(serializers.Serializer):
    def create(self, validated_data):
        raise NotImplementedError()

    def update(self, instance, validated_data):
        raise NotImplementedError()


class TokenBlacklistResponseSerializer(serializers.Serializer):
    def create(self, validated_data):
        raise NotImplementedError()

    def update(self, instance, validated_data):
        raise NotImplementedError()
