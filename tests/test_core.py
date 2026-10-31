import importlib
import sys
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum
from django.utils import timezone

from core.management.commands.seed_business_demo import SALES_COUNT
from core.models import (
    Alert,
    Batch,
    DeviceProvider,
    Forecast,
    Fridge,
    InventoryMovement,
    Location,
    Membership,
    Organization,
    Product,
    Sale,
    SaleItem,
    StockLocation,
    StockTransfer,
    StockTransferItem,
)
from core.services import balance, generate_forecasts, import_sales_csv, post_transfer


@pytest.fixture
def setup_data(db):
    org = Organization.objects.create(name="Тест")
    user = User.objects.create_user("owner", password="pass")
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    provider = DeviceProvider.objects.create(organization=org, code="TEST", name="Test")
    point = Location.objects.create(organization=org, name="Точка", address="Адрес")
    fridge = Fridge.objects.create(
        organization=org,
        location=point,
        provider=provider,
        name="Холодильник",
        serial_number="S1",
        external_id="F1",
    )
    warehouse = StockLocation.objects.create(
        organization=org, type=StockLocation.Type.WAREHOUSE, name="Склад"
    )
    fridge_stock = StockLocation.objects.create(
        organization=org, type=StockLocation.Type.FRIDGE, name="Холодильник", fridge=fridge
    )
    product = Product.objects.create(
        organization=org,
        sku="SKU1",
        name="Товар",
        cost_price=Decimal("100"),
        sale_price=Decimal("200"),
    )
    batch = Batch.objects.create(
        organization=org,
        product=product,
        batch_number="B1",
        expires_at=timezone.now() + timedelta(days=3),
    )
    InventoryMovement.objects.create(
        organization=org,
        stock_location=warehouse,
        product=product,
        batch=batch,
        movement_type=InventoryMovement.Type.INITIAL,
        quantity=20,
        unit_cost=product.cost_price,
        occurred_at=timezone.now(),
        source_type=InventoryMovement.Source.SYSTEM,
    )
    return org, user, provider, fridge, warehouse, fridge_stock, product, batch


@pytest.mark.django_db
def test_health(client):
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


def test_fridge_location_requires_fridge(db):
    org = Organization.objects.create(name="Тест")
    item = StockLocation(organization=org, type=StockLocation.Type.FRIDGE, name="Ошибка")
    with pytest.raises(ValidationError):
        item.full_clean()


def test_transfer_creates_two_movements(setup_data):
    org, user, _, _, warehouse, fridge_stock, product, batch = setup_data
    transfer = StockTransfer.objects.create(
        organization=org,
        source_location=warehouse,
        destination_location=fridge_stock,
        occurred_at=timezone.now(),
        created_by=user,
    )
    StockTransferItem.objects.create(
        transfer=transfer, product=product, batch=batch, quantity=5, unit_cost=Decimal("100")
    )
    post_transfer(transfer)
    assert balance(warehouse, product, batch) == 15
    assert balance(fridge_stock, product, batch) == 5
    assert InventoryMovement.objects.filter(transfer=transfer).count() == 2


def test_same_transfer_location_is_invalid(setup_data):
    org, user, _, _, warehouse, _, _, _ = setup_data
    transfer = StockTransfer(
        organization=org,
        source_location=warehouse,
        destination_location=warehouse,
        occurred_at=timezone.now(),
        created_by=user,
    )
    with pytest.raises(ValidationError):
        transfer.full_clean()


def test_csv_import_is_idempotent_and_fefo(setup_data):
    org, user, provider, fridge, _, fridge_stock, product, batch = setup_data
    InventoryMovement.objects.create(
        organization=org,
        stock_location=fridge_stock,
        product=product,
        batch=batch,
        movement_type=InventoryMovement.Type.INITIAL,
        quantity=4,
        unit_cost=product.cost_price,
        occurred_at=timezone.now() - timedelta(days=1),
        source_type=InventoryMovement.Source.SYSTEM,
    )
    data = (
        "provider_code,external_sale_id,sold_at,fridge_external_id,product_sku,"
        "quantity,unit_price,total_amount,payment_status,receipt_number\n"
        f"TEST,S1,{timezone.now().isoformat()},{fridge.external_id},SKU1,1,200.00,"
        "200.00,PAID,R1\n"
    ).encode()
    job, repeated = import_sales_csv(data, "sales.csv", org, provider, user)
    assert not repeated
    assert job.status == "COMMITTED"
    # Счётчики ограничены организацией: в тестовой базе могут лежать данные
    # других модульных фикстур (например, расширенного демо-набора).
    assert Sale.objects.filter(organization=org).count() == 1
    item = SaleItem.objects.filter(sale__organization=org).get()
    assert item.batch == batch
    assert item.batch_allocation_source == SaleItem.Allocation.ESTIMATED_FEFO
    assert balance(fridge_stock, product, batch) == 3

    _, repeated = import_sales_csv(data, "sales.csv", org, provider, user)
    assert repeated
    assert Sale.objects.filter(organization=org).count() == 1
    assert balance(fridge_stock, product, batch) == 3


def test_bad_csv_is_atomic(setup_data):
    org, user, provider, fridge, _, _, _, _ = setup_data
    data = (
        "provider_code,external_sale_id,sold_at,fridge_external_id,product_sku,"
        "quantity,unit_price,total_amount,payment_status,receipt_number\n"
        f"TEST,S1,{timezone.now().isoformat()},{fridge.external_id},UNKNOWN,1,200,200,PAID,R1\n"
    ).encode()
    job, _ = import_sales_csv(data, "bad.csv", org, provider, user)
    assert job.status == "FAILED"
    assert Sale.objects.filter(organization=org).count() == 0


@pytest.mark.django_db
def test_dashboard_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302


@pytest.mark.django_db
def test_seed_demo_is_idempotent():
    call_command("seed_demo")
    before_orgs = Organization.objects.filter(name="Демо-сеть микромаркетов").count()
    before_products = Product.objects.count()
    before_fridges = Fridge.objects.count()

    call_command("seed_demo")

    assert Organization.objects.filter(name="Демо-сеть микромаркетов").count() == before_orgs == 1
    assert Product.objects.count() == before_products
    assert Fridge.objects.count() == before_fridges == 7


@pytest.mark.django_db
def test_model_verbose_names():
    assert Organization._meta.verbose_name == "Организация"
    assert Organization._meta.verbose_name_plural == "Организации"
    assert Membership._meta.verbose_name == "Участник организации"
    assert Product._meta.verbose_name == "Товар"
    assert Product._meta.get_field("sku").verbose_name == "SKU"
    assert Product._meta.get_field("name").verbose_name == "наименование"
    assert Fridge._meta.verbose_name == "Холодильник"
    assert InventoryMovement._meta.verbose_name == "Движение товара"
    assert Sale._meta.verbose_name == "Продажа"
    assert Forecast._meta.verbose_name == "Рекомендация"
    assert Forecast._meta.get_field("forecast_date").verbose_name == "дата прогноза"
    assert Forecast._meta.get_field("replenish_quantity").verbose_name == "количество к пополнению"


@pytest.mark.django_db
def test_generate_forecasts_runs(setup_data):
    org, user, provider, fridge, _, _, product, batch = setup_data
    sale = Sale.objects.create(
        organization=org,
        provider=provider,
        fridge=fridge,
        external_id="S-forecast-1",
        sold_at=timezone.now(),
        total_amount=Decimal("200.00"),
        payment_status=Sale.PaymentStatus.PAID,
        receipt_number="R-forecast-1",
    )
    SaleItem.objects.create(
        sale=sale,
        product=product,
        batch=batch,
        batch_allocation_source=SaleItem.Allocation.ESTIMATED_FEFO,
        quantity=2,
        unit_price=Decimal("200.00"),
        unit_cost=product.cost_price,
    )
    target_date = timezone.localdate()
    created = generate_forecasts(org, target_date=target_date)
    assert Forecast.objects.filter(organization=org, forecast_date=target_date).exists()
    assert created
    assert all(item.replenish_quantity >= 0 for item in created)


@pytest.mark.django_db
def test_run_bot_without_aiogram():
    original = sys.modules.get("aiogram")
    with mock.patch.dict(
        sys.modules,
        {"aiogram": None, "aiogram.filters": None, "aiogram.types": None},
    ):
        module = importlib.import_module("core.management.commands.run_bot")
        importlib.reload(module)
        with pytest.raises(CommandError, match="Telegram-зависимости не установлены"):
            module.Command().handle()
    if original is not None:
        sys.modules["aiogram"] = original
    importlib.reload(importlib.import_module("core.management.commands.run_bot"))


@pytest.mark.django_db
@pytest.mark.slow
def test_seed_business_demo_generates_business_dataset():
    call_command("seed_business_demo")
    organization = Organization.objects.get(name="Демо-сеть микромаркетов")
    provider = DeviceProvider.objects.get(organization=organization, code="DEMO")

    assert Fridge.objects.filter(organization=organization, provider=provider).count() == 7
    assert Product.objects.filter(organization=organization).count() == 10
    sales = Sale.objects.filter(organization=organization, external_id__startswith="SYNTH-")
    assert sales.count() == SALES_COUNT

    earliest = timezone.now() - timedelta(days=60)
    assert sales.filter(sold_at__gt=timezone.now()).count() == 0
    assert sales.filter(sold_at__lt=earliest).count() == 0

    paid_sales = sales.filter(payment_status=Sale.PaymentStatus.PAID)
    revenue_60 = paid_sales.aggregate(total=Sum("total_amount"))["total"] or Decimal("0")
    assert Decimal("1550000") <= revenue_60 <= Decimal("1750000")

    last_30 = timezone.now() - timedelta(days=30)
    last_30_revenue = paid_sales.filter(sold_at__gte=last_30).aggregate(total=Sum("total_amount"))["total"] or Decimal("0")
    assert Decimal("750000") <= last_30_revenue <= Decimal("900000")

    avg_check = revenue_60 / Decimal(paid_sales.count() or 1)
    assert Decimal("380") <= avg_check <= Decimal("430")

    bad_balances = InventoryMovement.objects.filter(organization=organization).values_list("stock_location_id", "product_id", "batch_id").annotate(total=Sum("quantity"))
    assert all(item[3] >= 0 for item in bad_balances)

    write_offs = InventoryMovement.objects.filter(
        organization=organization,
        movement_type=InventoryMovement.Type.WRITE_OFF,
        occurred_at__gte=last_30,
        external_id__startswith="SYNTH:",
    )
    assert write_offs.exists()
    write_off_total = sum((abs(item.quantity) * item.unit_cost for item in write_offs), Decimal("0"))
    ratio = (write_off_total / last_30_revenue * Decimal("100")) if last_30_revenue else Decimal("0")
    assert Decimal("5") <= ratio <= Decimal("8")

    assert Batch.objects.filter(
        organization=organization,
        status=Batch.Status.ACTIVE,
        expires_at__lte=timezone.now() + timedelta(days=2),
    ).exists()
    assert Forecast.objects.filter(
        organization=organization, model_version="weighted-v1", explanation__demo_source="business_demo"
    ).exists()
    assert Alert.objects.filter(organization=organization, status="OPEN").exists()


@pytest.mark.django_db
def test_seed_business_demo_is_idempotent_without_replace():
    out = StringIO()
    call_command("seed_business_demo", stdout=out)
    sales_count = Sale.objects.filter(organization=Organization.objects.get(name="Демо-сеть микромаркетов"), external_id__startswith="SYNTH-").count()
    assert sales_count == SALES_COUNT

    second_output = StringIO()
    call_command("seed_business_demo", stdout=second_output)
    assert "Расширенные демонстрационные данные уже созданы" in second_output.getvalue()
    assert Sale.objects.filter(organization=Organization.objects.get(name="Демо-сеть микромаркетов"), external_id__startswith="SYNTH-").count() == sales_count


@pytest.mark.django_db
def test_seed_business_demo_replace_only_removes_synthetic_data():
    call_command("seed_business_demo")
    organization = Organization.objects.get(name="Демо-сеть микромаркетов")
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
    other_sale = Sale.objects.create(
        organization=other_org,
        provider=other_provider,
        fridge=other_fridge,
        external_id="REAL-001",
        sold_at=timezone.now(),
        total_amount=Decimal("100"),
        payment_status=Sale.PaymentStatus.PAID,
        receipt_number="REAL-001",
    )
    other_batch = Batch.objects.create(
        organization=other_org,
        product=other_product,
        batch_number="REAL-BATCH-001",
        expires_at=timezone.now() + timedelta(days=10),
    )
    InventoryMovement.objects.create(
        organization=other_org,
        stock_location=StockLocation.objects.create(organization=other_org, type=StockLocation.Type.WAREHOUSE, name="Склад другого бизнеса"),
        product=other_product,
        batch=other_batch,
        movement_type=InventoryMovement.Type.RECEIPT,
        quantity=30,
        unit_cost=other_product.cost_price,
        occurred_at=timezone.now(),
        source_type=InventoryMovement.Source.SYSTEM,
    )

    call_command("seed_business_demo", replace=True)

    assert Organization.objects.filter(pk=other_org.pk).exists()
    assert Sale.objects.filter(pk=other_sale.pk).exists()
    assert Batch.objects.filter(pk=other_batch.pk).exists()
    assert Product.objects.filter(pk=other_product.pk).exists()
    assert Sale.objects.filter(organization=organization, external_id__startswith="SYNTH-").count() == SALES_COUNT
