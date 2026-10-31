from django.urls import path

from . import portal, views

urlpatterns = [
    path("records/<str:section>/", portal.records, name="records"),
    path("health/", views.health, name="health"),
    path("", views.dashboard, name="dashboard"),
    path("imports/sales/", views.sales_import, name="sales_import"),
    path("forecasts/generate/", views.forecasts_generate, name="forecasts_generate"),
]
