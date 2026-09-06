from django.urls import path

from apps.core import enums_api
from apps.identity import api

urlpatterns = [
    path("me", api.me, name="me"),
    path("me/password", api.change_password, name="change-password"),
    path("logout", api.logout, name="logout"),
    path("enums", enums_api.enums, name="enums"),
]
