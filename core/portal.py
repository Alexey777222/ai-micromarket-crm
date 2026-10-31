"""Read-only owner screens; queries scoped to the active organization."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from .models import Batch, Forecast, Fridge, InventoryMovement, Product, Sale
from .views import _organization_for


def _date(value):
    return timezone.localtime(value).strftime("%d.%m.%Y %H:%M") if value else "—"


@login_required
def records(request, section):
    organization = _organization_for(request.user)
    if not organization:
        return render(request, "core/no_organization.html")
    term = request.GET.get("q", "").strip()[:100]
    base = {"organization": organization}
    if section == "fridges":
        title, headers = "Холодильники", ["Название", "Площадка", "Модель", "Статус"]
        query = Fridge.objects.filter(**base).select_related("location").order_by("name", "id")
        if term:
            query = query.filter(Q(name__icontains=term) | Q(location__name__icontains=term))
        def row(x):
            return [x.name, x.location.name, x.model or "—", x.get_status_display()]
    elif section == "products":
        title, headers = "Товары", ["SKU", "Наименование", "Категория", "Себестоимость, ₽", "Цена, ₽"]
        query = Product.objects.filter(**base).order_by("name", "id")
        if term:
            query = query.filter(Q(name__icontains=term) | Q(sku__icontains=term))
        def row(x):
            return [x.sku, x.name, x.category, x.cost_price, x.sale_price]
    elif section == "batches":
        title, headers = "Партии и сроки", ["Товар", "Партия", "Годен до", "Статус"]
        query = Batch.objects.filter(**base).select_related("product").order_by("expires_at", "id")
        if term:
            query = query.filter(Q(product__name__icontains=term) | Q(batch_number__icontains=term))
        def row(x):
            return [x.product.name, x.batch_number, _date(x.expires_at),
                    "Просрочена по дате" if x.expires_at <= timezone.now() else x.get_status_display()]
    elif section == "sales":
        title, headers = "Продажи", ["Дата", "Холодильник", "ID продажи", "Сумма, ₽", "Статус"]
        query = Sale.objects.filter(**base).select_related("fridge").order_by("-sold_at", "-id")
        if term:
            query = query.filter(Q(fridge__name__icontains=term) | Q(external_id__icontains=term))
        def row(x):
            return [_date(x.sold_at), x.fridge.name, x.external_id, x.total_amount, x.get_payment_status_display()]
    elif section == "writeoffs":
        title, headers = "Списания", ["Дата", "Место", "Товар", "Количество", "Стоимость, ₽", "Причина"]
        query = InventoryMovement.objects.filter(
            **base, movement_type=InventoryMovement.Type.WRITE_OFF,
        ).select_related("stock_location", "product").order_by("-occurred_at", "-id")
        if term:
            query = query.filter(Q(product__name__icontains=term) | Q(stock_location__name__icontains=term))
        def row(x):
            return [_date(x.occurred_at), x.stock_location.name, x.product.name,
                    abs(x.quantity), abs(x.quantity * x.unit_cost), x.reason]
    elif section == "stock":
        title, headers = "Расчётные остатки", ["Место хранения", "Товар", "Партия", "Годен до", "Количество"]
        query = InventoryMovement.objects.filter(**base).exclude(stock_location__type="WRITE_OFF_ZONE")
        if term:
            query = query.filter(Q(product__name__icontains=term) | Q(stock_location__name__icontains=term))
        query = query.values(
            "stock_location_id", "product_id", "batch_id",
            "stock_location__name", "product__name", "batch__batch_number", "batch__expires_at",
        ).annotate(total=Sum("quantity")).exclude(total=0).order_by(
            "stock_location__name", "product__name", "batch__batch_number", "batch_id",
        )
        def row(x):
            return [x["stock_location__name"], x["product__name"], x["batch__batch_number"] or "Без партии",
                    _date(x["batch__expires_at"]), x["total"]]
    elif section == "forecasts":
        title, headers = "Рекомендации по пополнению", ["Дата", "Холодильник", "Товар", "Прогноз спроса", "К пополнению"]
        latest = Forecast.objects.filter(**base, forecast_date__gte=timezone.localdate()).order_by(
            "-forecast_date",
        ).values_list("forecast_date", flat=True).first()
        query = Forecast.objects.filter(**base, forecast_date=latest, replenish_quantity__gt=0).select_related(
            "fridge", "product",
        ).order_by("-replenish_quantity", "fridge__name", "product__name", "id")
        if term:
            query = query.filter(Q(fridge__name__icontains=term) | Q(product__name__icontains=term))
        def row(x):
            return [x.forecast_date.strftime("%d.%m.%Y"), x.fridge.name, x.product.name,
                    x.predicted_quantity, x.replenish_quantity]
    else:
        raise Http404
    page = Paginator(query, 30).get_page(request.GET.get("page"))
    return render(request, "core/records.html", {
        "organization": organization, "title": title, "headers": headers,
        "rows": [row(item) for item in page], "page": page, "q": term, "section": section,
    })
