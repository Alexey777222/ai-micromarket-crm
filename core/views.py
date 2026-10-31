from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connection
from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import SalesImportForm
from .models import (
    Batch,
    Forecast,
    Fridge,
    ImportJob,
    InventoryMovement,
    Membership,
    Sale,
    SaleItem,
)
from .services import generate_forecasts, import_sales_csv


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})


def _organization_for(user):
    memberships = list(Membership.objects.select_related("organization").filter(
        user=user, organization__is_active=True
    )[:2])
    if len(memberships) > 1:
        raise PermissionDenied("В пилоте у пользователя должна быть одна активная организация.")
    return memberships[0].organization if memberships else None


def _require_operator(user, organization):
    if not Membership.objects.filter(
        user=user, organization=organization,
        role__in=[Membership.Role.OWNER, Membership.Role.OPERATOR],
    ).exists():
        raise PermissionDenied("Действие доступно владельцу или оператору.")


@login_required
def dashboard(request):
    organization = _organization_for(request.user)
    if not organization:
        return render(request, "core/no_organization.html")
    now = timezone.now()
    since_30 = now - timedelta(days=30)
    sales = Sale.objects.filter(
        organization=organization,
        sold_at__gte=since_30,
        payment_status=Sale.PaymentStatus.PAID,
    )
    revenue = sales.aggregate(value=Sum("total_amount"))["value"] or Decimal("0")
    # Себестоимость берём из позиции продажи, а при её отсутствии — из справочника,
    # иначе пустой unit_cost молча занижит себестоимость и завысит маржу.
    items = SaleItem.objects.filter(sale__in=sales).annotate(
        cost=Coalesce(F("unit_cost"), F("product__cost_price")) * F("quantity")
    )
    cost = items.aggregate(value=Sum("cost"))["value"] or Decimal("0")
    gross_profit = revenue - cost
    writeoffs = InventoryMovement.objects.filter(
        organization=organization,
        movement_type=InventoryMovement.Type.WRITE_OFF,
        occurred_at__gte=since_30,
    ).annotate(loss=F("unit_cost") * F("quantity"))
    writeoff_cost = abs(writeoffs.aggregate(value=Sum("loss"))["value"] or Decimal("0"))
    expiring = Batch.objects.filter(
        organization=organization,
        status=Batch.Status.ACTIVE,
        expires_at__gt=now,
        expires_at__lte=now + timedelta(hours=48),
    ).select_related("product")[:20]
    # Рекомендации показываются только для самой поздней даты прогноза и только
    # с положительным пополнением: прогнозы разных дат или версий модели не должны
    # дублировать пару «холодильник + товар» в таблице.
    latest_forecast_date = (
        Forecast.objects.filter(
            organization=organization,
            forecast_date__gte=timezone.localdate(),
        )
        .order_by("-forecast_date")
        .values_list("forecast_date", flat=True)
        .first()
    )
    forecasts = (
        Forecast.objects.filter(
            organization=organization,
            forecast_date=latest_forecast_date,
            replenish_quantity__gt=0,
        )
        .select_related("fridge", "product")
        .order_by("-replenish_quantity", "fridge__name")[:30]
    )
    imports = ImportJob.objects.filter(organization=organization).order_by("-created_at")[:5]
    by_fridge = (
        sales.values("fridge__name").annotate(revenue=Sum("total_amount")).order_by("-revenue")
    )
    context = {
        "organization": organization,
        "fridge_count": Fridge.objects.filter(organization=organization).count(),
        "revenue": revenue,
        "gross_profit": gross_profit,
        "gross_margin": (gross_profit / revenue * 100) if revenue else Decimal("0"),
        "writeoff_cost": writeoff_cost,
        "writeoff_percent": (writeoff_cost / revenue * 100) if revenue else Decimal("0"),
        "expiring": expiring,
        "forecasts": forecasts,
        "forecast_date": latest_forecast_date,
        "imports": imports,
        "by_fridge": by_fridge,
    }
    return render(request, "core/dashboard.html", context)


@login_required
def sales_import(request):
    organization = _organization_for(request.user)
    if not organization:
        return render(request, "core/no_organization.html")
    _require_operator(request.user, organization)
    if request.method == "POST":
        form = SalesImportForm(request.POST, request.FILES, organization=organization)
        if form.is_valid():
            upload = form.cleaned_data["file"]
            job, repeated_file = import_sales_csv(
                upload.read(),
                upload.name,
                organization,
                form.cleaned_data["provider"],
                request.user,
            )
            if repeated_file:
                messages.info(request, "Этот файл уже был импортирован. Дубли не созданы.")
            elif job.status == ImportJob.Status.FAILED:
                messages.error(request, f"Импорт отклонён: найдено ошибок — {job.error_rows}.")
            else:
                messages.success(
                    request,
                    f"Импорт завершён. Строк: {job.total_rows}, дублей: {job.duplicate_rows}.",
                )
            return redirect("sales_import")
    else:
        form = SalesImportForm(organization=organization)
    jobs = ImportJob.objects.filter(organization=organization).order_by("-created_at")[:20]
    return render(request, "core/import.html", {"form": form, "jobs": jobs})


@login_required
@require_POST
def forecasts_generate(request):
    organization = _organization_for(request.user)
    if request.method == "POST" and organization:
        _require_operator(request.user, organization)
        forecasts = generate_forecasts(organization)
        messages.success(request, f"Создано рекомендаций к пополнению: {len(forecasts)}.")
    return redirect("dashboard")
