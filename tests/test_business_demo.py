"""Аудит расширенного демонстрационного набора MicroMarket Control.

Генерация набора дорогая, поэтому выполняется один раз на модуль: ``--replace``
детерминирован, а все проверки работают с одним и тем же состоянием базы.
Тесты проверяют экономическую согласованность показателей, правдоподобие
остатков, разнообразие рекомендаций и безопасность повторного ``--replace``.
"""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db.models import Count, F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.management.commands.seed_business_demo import (
    CANCELLED_SALES_COUNT,
    REFUNDED_SALES_COUNT,
    SALES_COUNT,
)
from core.models import (
    Alert,
    Batch,
    DeviceProvider,
    Forecast,
    Fridge,
    InventoryMovement,
    Location,
    Organization,
    Product,
    Sale,
    SaleItem,
    StockLocation,
)
from core.services import generate_forecasts

DEMO_ORG_NAME = "Демо-сеть микромаркетов"
DASHBOARD_FORECAST_LIMIT = 30


@pytest.fixture(scope="module")
def demo_organization(django_db_setup, django_db_blocker):
    """Один детерминированный прогон генератора на весь модуль.

    Тестовая база pytest-django пересоздаётся при каждом запуске, поэтому
    после модуля данные не удаляются: каскадное удаление организации всё равно
    заблокировано PROTECT-связями партий и движений.
    """
    with django_db_blocker.unblock():
        call_command("seed_business_demo", "--replace", stdout=StringIO())
        yield Organization.objects.get(name=DEMO_ORG_NAME)


def paid_sales_last_30(organization):
    return Sale.objects.filter(
        organization=organization,
        payment_status=Sale.PaymentStatus.PAID,
        sold_at__gte=timezone.now() - timedelta(days=30),
    )


def revenue_and_cogs(organization):
    """Выручка и себестоимость проданных за 30 дней — как на дашборде."""
    sales = paid_sales_last_30(organization)
    revenue = sales.aggregate(value=Sum("total_amount"))["value"] or Decimal("0")
    cogs = (
        SaleItem.objects.filter(sale__in=sales)
        .annotate(item_cost=Coalesce(F("unit_cost"), F("product__cost_price")) * F("quantity"))
        .aggregate(value=Sum("item_cost"))["value"]
        or Decimal("0")
    )
    return revenue, cogs


def fridge_totals(organization):
    return {
        fridge.name: (
            InventoryMovement.objects.filter(
                stock_location=StockLocation.objects.get(fridge=fridge)
            ).aggregate(value=Sum("quantity"))["value"]
            or 0
        )
        for fridge in Fridge.objects.filter(organization=organization)
    }


def dashboard_forecasts(organization):
    """Выборка рекомендаций ровно та же, что отдаёт дашборд: последняя дата."""
    latest_date = (
        Forecast.objects.filter(
            organization=organization,
            forecast_date__gte=timezone.localdate(),
        )
        .order_by("-forecast_date")
        .values_list("forecast_date", flat=True)
        .first()
    )
    return Forecast.objects.filter(
        organization=organization,
        forecast_date=latest_date,
        replenish_quantity__gt=0,
    ).order_by("-replenish_quantity", "fridge__name")[:DASHBOARD_FORECAST_LIMIT]


@pytest.mark.django_db
@pytest.mark.slow
def test_dataset_shape(demo_organization):
    organization = demo_organization
    assert Fridge.objects.filter(organization=organization).count() == 7
    assert Product.objects.filter(organization=organization).count() == 10

    sales = Sale.objects.filter(organization=organization, external_id__startswith="SYNTH-")
    assert sales.count() == SALES_COUNT
    assert sales.filter(sold_at__gt=timezone.now()).count() == 0
    assert sales.filter(sold_at__lt=timezone.now() - timedelta(days=60)).count() == 0

    assert Forecast.objects.filter(
        organization=organization, model_version="weighted-v1", explanation__demo_source="business_demo"
    ).exists()
    assert Alert.objects.filter(organization=organization, status="OPEN").exists()


@pytest.mark.django_db
@pytest.mark.slow
def test_exactly_4100_synthetic_sales_with_specified_statuses(demo_organization):
    """Ровно 4100 синтетических продаж: 4059 PAID, 25 CANCELLED, 16 REFUNDED."""
    organization = demo_organization
    sales = Sale.objects.filter(organization=organization, external_id__startswith="SYNTH-")
    assert sales.count() == SALES_COUNT == 4100

    statuses = dict(
        sales.values("payment_status")
        .annotate(count=Count("id"))
        .values_list("payment_status", "count")
    )
    expected = {
        Sale.PaymentStatus.PAID: SALES_COUNT - CANCELLED_SALES_COUNT - REFUNDED_SALES_COUNT,
        Sale.PaymentStatus.CANCELLED: CANCELLED_SALES_COUNT,
        Sale.PaymentStatus.REFUNDED: REFUNDED_SALES_COUNT,
    }
    assert statuses == expected

    # Идентификаторы — ровно SYNTH-000001..SYNTH-004100, без пропусков и выхода за диапазон.
    numbers = sorted(int(external_id.split("-")[1]) for external_id in sales.values_list("external_id", flat=True))
    assert numbers == list(range(1, SALES_COUNT + 1))
    assert max(numbers) == 4100


@pytest.mark.django_db
@pytest.mark.slow
def test_revenue_ranges_30_and_60_days(demo_organization):
    """Выручка оплаченных продаж входит в целевые диапазоны технического задания."""
    organization = demo_organization
    paid = Sale.objects.filter(
        organization=organization,
        payment_status=Sale.PaymentStatus.PAID,
        external_id__startswith="SYNTH-",
    )
    revenue_60 = paid.filter(sold_at__gte=timezone.now() - timedelta(days=60)).aggregate(
        total=Sum("total_amount")
    )["total"] or Decimal("0")
    revenue_30 = paid.filter(sold_at__gte=timezone.now() - timedelta(days=30)).aggregate(
        total=Sum("total_amount")
    )["total"] or Decimal("0")
    assert Decimal("1550000") <= revenue_60 <= Decimal("1750000")
    assert Decimal("750000") <= revenue_30 <= Decimal("900000")


@pytest.mark.django_db
@pytest.mark.slow
def test_paid_sale_items_have_positive_cost_from_catalog(demo_organization):
    """У всех оплаченных позиций себестоимость заполнена, положительна и равна справочной."""
    items = SaleItem.objects.filter(sale__in=paid_sales_last_30(demo_organization))
    assert items.exists()
    assert not items.filter(unit_cost__isnull=True).exists()
    assert not items.filter(unit_cost__lte=0).exists()
    mismatched = items.select_related("product").annotate(expected=F("product__cost_price")).exclude(
        unit_cost=F("expected")
    )
    assert not mismatched.exists()


@pytest.mark.django_db
@pytest.mark.slow
def test_sale_total_equals_sum_of_position_values(demo_organization):
    """Сумма продажи совпадает с суммой позиций: иначе маржа на дашборде нереальна."""
    mismatched = 0
    for sale in paid_sales_last_30(demo_organization).prefetch_related("items").iterator(chunk_size=500):
        line_total = sum(
            (item.unit_price * Decimal(item.quantity) for item in sale.items.all()),
            Decimal("0.00"),
        )
        if line_total != sale.total_amount:
            mismatched += 1
    assert mismatched == 0


@pytest.mark.django_db
@pytest.mark.slow
def test_gross_margin_is_realistic(demo_organization):
    """Валовая маржа за 30 дней лежит в правдоподобном для общепита диапазоне 40–65%."""
    revenue, cogs = revenue_and_cogs(demo_organization)
    assert revenue > 0
    assert cogs > 0
    assert cogs < revenue
    margin = (revenue - cogs) / revenue * Decimal("100")
    assert Decimal("40") <= margin <= Decimal("65")


@pytest.mark.django_db
@pytest.mark.slow
def test_write_off_share_is_realistic(demo_organization):
    """Списания за 30 дней составляют 5–8% выручки."""
    organization = demo_organization
    revenue, _ = revenue_and_cogs(organization)
    write_off_cost = sum(
        (
            abs(row.quantity) * row.unit_cost
            for row in InventoryMovement.objects.filter(
                organization=organization,
                movement_type=InventoryMovement.Type.WRITE_OFF,
                occurred_at__gte=timezone.now() - timedelta(days=30),
            )
        ),
        Decimal("0"),
    )
    assert write_off_cost > 0
    ratio = write_off_cost / revenue * Decimal("100")
    assert Decimal("5") <= ratio <= Decimal("8")


@pytest.mark.django_db
@pytest.mark.slow
def test_fridge_stocks_are_positive_and_realistic(demo_organization):
    """Остаток каждого холодильника положителен и лежит в диапазоне 90–120 единиц."""
    totals = fridge_totals(demo_organization)
    assert len(totals) == 7
    for name, total in totals.items():
        assert total > 0, name
        assert 90 <= total <= 120, f"{name}: {total}"


@pytest.mark.django_db
@pytest.mark.slow
def test_stocks_are_not_uniform_across_products(demo_organization):
    """Остатки распределены между товарами неравномерно, а не «всем поровну»."""
    per_product = list(
        InventoryMovement.objects.filter(
            stock_location__in=StockLocation.objects.filter(fridge__isnull=False)
        )
        .values("product__sku")
        .annotate(total=Sum("quantity"))
    )
    assert per_product
    values = [row["total"] for row in per_product]
    assert len(set(values)) > 1


@pytest.mark.django_db
@pytest.mark.slow
def test_no_negative_balances(demo_organization):
    """Ни одна партия ни в одном месте хранения не уходит в минус."""
    negative = list(
        InventoryMovement.objects.filter(organization=demo_organization)
        .values("stock_location_id", "product_id", "batch_id")
        .annotate(total=Sum("quantity"))
        .filter(total__lt=0)
    )
    assert negative == []


@pytest.mark.django_db
@pytest.mark.slow
def test_recommendations_vary_and_not_every_product_needs_replenishment(demo_organization):
    """Рекомендации разнообразны, и часть товаров обеспечена запасом."""
    forecasts = Forecast.objects.filter(
        organization=demo_organization, forecast_date__gte=timezone.localdate()
    )
    assert forecasts.exists()

    quantities = list(forecasts.filter(replenish_quantity__gt=0).values_list("replenish_quantity", flat=True))
    assert len(set(quantities)) >= 5, sorted(set(quantities))
    # Не каждый товар требует немедленного пополнения.
    assert forecasts.filter(replenish_quantity=0).exists()
    assert len(quantities) < forecasts.count()


@pytest.mark.django_db
@pytest.mark.slow
def test_dashboard_forecasts_show_various_quantities(demo_organization):
    """На дашборде видно не менее пяти различных количеств пополнения."""
    quantities = {row.replenish_quantity for row in dashboard_forecasts(demo_organization)}
    assert len(quantities) >= 5, sorted(quantities)


@pytest.mark.django_db
@pytest.mark.slow
def test_expiring_batches_are_only_synthetic(demo_organization):
    """В списке истекающих партий только партии расширенного набора."""
    now = timezone.now()
    expiring = Batch.objects.filter(
        organization=demo_organization,
        status=Batch.Status.ACTIVE,
        expires_at__gt=now,
        expires_at__lte=now + timedelta(hours=48),
    )
    numbers = list(expiring.values_list("batch_number", flat=True))
    assert numbers
    assert all(number.startswith("SYNTH-BATCH-") for number in numbers), numbers
    assert not Batch.objects.filter(
        organization=demo_organization, batch_number__startswith="DEMO-"
    ).exists()


@pytest.mark.django_db
@pytest.mark.slow
def test_dashboard_opens_without_errors(demo_organization, client):
    user = User.objects.get(username="demo")
    client.force_login(user)
    response = client.get("/")
    assert response.status_code == 200
    content = response.content.decode()
    assert DEMO_ORG_NAME in content
    assert "маржа" in content
    # Заголовок таблицы рекомендаций содержит дату прогноза.
    assert "Рекомендации на пополнение на" in content

    # В контексте дашборда нет повторяющихся пар «холодильник + товар».
    forecasts = response.context["forecasts"]
    pairs = [(row.fridge_id, row.product_id) for row in forecasts]
    assert len(pairs) == len(set(pairs)), pairs
    # Все рекомендации — одной даты и только с положительным пополнением.
    assert len({row.forecast_date for row in forecasts}) <= 1
    assert all(row.replenish_quantity > 0 for row in forecasts)


@pytest.mark.django_db
@pytest.mark.slow
def test_single_forecast_per_pair_on_latest_date(demo_organization):
    """На актуальную дату существует не более одной рекомендации на пару холодильник–товар."""
    organization = demo_organization
    latest_date = (
        Forecast.objects.filter(organization=organization, forecast_date__gte=timezone.localdate())
        .order_by("-forecast_date")
        .values_list("forecast_date", flat=True)
        .first()
    )
    assert latest_date is not None
    duplicates = list(
        Forecast.objects.filter(organization=organization, forecast_date=latest_date)
        .values("fridge_id", "product_id")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
    )
    assert duplicates == []
    # Используется единственная версия модели.
    versions = set(
        Forecast.objects.filter(organization=organization, forecast_date__gte=timezone.localdate()).values_list(
            "model_version", flat=True
        )
    )
    assert versions == {"weighted-v1"}


@pytest.mark.django_db
@pytest.mark.slow
def test_repeated_forecast_generation_creates_no_duplicates(demo_organization):
    """Повторный расчёт пополнения не увеличивает количество записей."""
    organization = demo_organization
    before = Forecast.objects.filter(organization=organization).count()
    assert before > 0

    generate_forecasts(organization)
    generate_forecasts(organization)

    after = Forecast.objects.filter(organization=organization).count()
    assert after == before
    duplicates = list(
        Forecast.objects.filter(organization=organization)
        .values("fridge_id", "product_id", "forecast_date", "model_version")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
    )
    assert duplicates == []


@pytest.mark.django_db
@pytest.mark.slow
def test_replace_adds_no_duplicates_and_keeps_other_organizations(demo_organization):
    """Повторный ``--replace`` не создаёт дублей и не трогает чужие данные."""
    organization = demo_organization

    other_org = Organization.objects.create(name="Другой бизнес")
    other_provider = DeviceProvider.objects.create(organization=other_org, code="OTHER", name="Other")
    other_fridge = Fridge.objects.create(
        organization=other_org,
        location=Location.objects.create(organization=other_org, name="Другая точка", address="Москва, другой адрес"),
        provider=other_provider,
        name="Другое оборудование",
        serial_number="OTH-001",
        external_id="OTHER-001",
    )
    other_product = Product.objects.create(
        organization=other_org,
        sku="OTHER-ITEM",
        name="Другой товар",
        cost_price=Decimal("50"),
        sale_price=Decimal("100"),
    )
    other_batch = Batch.objects.create(
        organization=other_org,
        product=other_product,
        batch_number="REAL-BATCH-001",
        expires_at=timezone.now() + timedelta(days=10),
    )
    other_sale = Sale.objects.create(
        organization=other_org,
        provider=other_provider,
        fridge=other_fridge,
        external_id="REAL-001",
        sold_at=timezone.now(),
        total_amount=Decimal("100.00"),
        payment_status=Sale.PaymentStatus.PAID,
        receipt_number="REAL-001",
    )

    # Пользовательская продажа в демо-организации, но через своего провайдера:
    # она не входит в демо-набор и не должна удаляться.
    user_provider = DeviceProvider.objects.create(organization=organization, code="USER-CODE", name="Пользовательский")
    demo_fridge = Fridge.objects.filter(organization=organization).first()
    user_sale = Sale.objects.create(
        organization=organization,
        provider=user_provider,
        fridge=demo_fridge,
        external_id="USER-SALE-001",
        sold_at=timezone.now(),
        total_amount=Decimal("150.00"),
        payment_status=Sale.PaymentStatus.PAID,
        receipt_number="USER-001",
    )
    # Продажа демо-CSV-импорта (демо-провайдер, без SYNTH-) — часть старого
    # демо-набора и удаляется при --replace.
    demo_provider = DeviceProvider.objects.get(organization=organization, code="DEMO")
    demo_import_sale = Sale.objects.create(
        organization=organization,
        provider=demo_provider,
        fridge=demo_fridge,
        external_id="S-99999",
        sold_at=timezone.now(),
        total_amount=Decimal("100.00"),
        payment_status=Sale.PaymentStatus.PAID,
        receipt_number="99999",
    )

    def snapshot():
        return {
            "sales": Sale.objects.filter(organization=organization).count(),
            "items": SaleItem.objects.filter(sale__organization=organization).count(),
            "movements": InventoryMovement.objects.filter(organization=organization).count(),
            "batches": Batch.objects.filter(organization=organization).count(),
            "forecasts": Forecast.objects.filter(organization=organization).count(),
            "alerts": Alert.objects.filter(organization=organization).count(),
        }

    before = snapshot()
    call_command("seed_business_demo", "--replace", stdout=StringIO())
    after = snapshot()

    # Чужая организация и её данные остались нетронутыми.
    assert Organization.objects.filter(pk=other_org.pk).exists()
    assert Sale.objects.filter(pk=other_sale.pk).exists()
    assert Batch.objects.filter(pk=other_batch.pk).exists()
    assert Product.objects.filter(pk=other_product.pk).exists()

    # Пользовательская продажа в демо-организации сохранена,
    # продажа демо-импорта удалена — объём уменьшился ровно на неё.
    assert Sale.objects.filter(pk=user_sale.pk).exists()
    assert not Sale.objects.filter(pk=demo_import_sale.pk).exists()
    assert after["sales"] == before["sales"] - 1
    assert {k: v for k, v in after.items() if k != "sales"} == {
        k: v for k, v in before.items() if k != "sales"
    }

    # Повторный --replace ничего не меняет: задвоений нет.
    call_command("seed_business_demo", "--replace", stdout=StringIO())
    assert snapshot() == after
    sales = Sale.objects.filter(organization=organization, external_id__startswith="SYNTH-")
    assert sales.count() == sales.values("external_id").distinct().count() == SALES_COUNT
    # С учётом сохранённой пользовательской продажи — ровно 4100 синтетических.
    assert Sale.objects.filter(organization=organization).count() == SALES_COUNT + 1
