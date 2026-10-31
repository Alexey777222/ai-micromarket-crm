"""Проверки стандартного seed_demo и demo_sales.csv."""

from io import StringIO

import pytest
from django.core.management import call_command

from core.models import (
    Batch,
    DeviceProvider,
    Fridge,
    InventoryMovement,
    Organization,
    Product,
    StockLocation,
)

DEMO_ORG_NAME = "Демо-сеть микромаркетов"
DEMO_SALES_CSV = "samples/demo_sales.csv"


@pytest.mark.django_db
def test_seed_demo_creates_organization():
    call_command("seed_demo")
    assert Organization.objects.filter(name=DEMO_ORG_NAME).exists()


@pytest.mark.django_db
def test_seed_demo_creates_demo_user():
    from django.contrib.auth.models import User

    call_command("seed_demo")
    user = User.objects.get(username="demo")
    assert user.is_staff is True
    assert user.is_superuser is True


@pytest.mark.django_db
def test_seed_demo_creates_7_fridges():
    call_command("seed_demo")
    org = Organization.objects.get(name=DEMO_ORG_NAME)
    assert Fridge.objects.filter(organization=org).count() == 7


@pytest.mark.django_db
def test_seed_demo_creates_10_products():
    call_command("seed_demo")
    org = Organization.objects.get(name=DEMO_ORG_NAME)
    assert Product.objects.filter(organization=org).count() == 10


@pytest.mark.django_db
def test_seed_demo_creates_warehouse():
    call_command("seed_demo")
    org = Organization.objects.get(name=DEMO_ORG_NAME)
    wh = StockLocation.objects.filter(organization=org, type=StockLocation.Type.WAREHOUSE)
    assert wh.exists()


@pytest.mark.django_db
def test_seed_demo_creates_writeoff_zone():
    call_command("seed_demo")
    org = Organization.objects.get(name=DEMO_ORG_NAME)
    zone = StockLocation.objects.filter(organization=org, type=StockLocation.Type.WRITE_OFF_ZONE)
    assert zone.exists()


@pytest.mark.django_db
def test_seed_demo_creates_fridge_locations():
    call_command("seed_demo")
    org = Organization.objects.get(name=DEMO_ORG_NAME)
    fridge_locs = StockLocation.objects.filter(organization=org, type=StockLocation.Type.FRIDGE)
    assert fridge_locs.count() == 7


@pytest.mark.django_db
def test_seed_demo_creates_batches():
    call_command("seed_demo")
    org = Organization.objects.get(name=DEMO_ORG_NAME)
    assert Batch.objects.filter(organization=org).exists()


@pytest.mark.django_db
def test_seed_demo_creates_initial_movements():
    call_command("seed_demo")
    org = Organization.objects.get(name=DEMO_ORG_NAME)
    movements = InventoryMovement.objects.filter(
        organization=org, movement_type=InventoryMovement.Type.INITIAL
    )
    assert movements.exists()


@pytest.mark.django_db
def test_seed_demo_idempotent():
    call_command("seed_demo")
    org = Organization.objects.get(name=DEMO_ORG_NAME)
    fridges_before = Fridge.objects.filter(organization=org).count()
    products_before = Product.objects.filter(organization=org).count()
    call_command("seed_demo")
    assert Fridge.objects.filter(organization=org).count() == fridges_before
    assert Product.objects.filter(organization=org).count() == products_before


@pytest.mark.django_db
def test_seed_demo_demo_provider_exists():
    call_command("seed_demo")
    org = Organization.objects.get(name=DEMO_ORG_NAME)
    assert DeviceProvider.objects.filter(organization=org, code="DEMO").exists()


@pytest.mark.django_db
def test_seed_demo_output_message():
    out = StringIO()
    call_command("seed_demo", stdout=out)
    text = out.getvalue()
    assert "demo" in text
    assert "demo12345" in text


@pytest.mark.django_db
def test_demo_csv_can_be_parsed():
    """Проверяем, что samples/demo_sales.csv содержит корректный заголовок."""
    from pathlib import Path

    from django.conf import settings

    csv_path = Path(settings.BASE_DIR) / DEMO_SALES_CSV
    assert csv_path.exists(), f"{DEMO_SALES_CSV} не найден"
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    header = lines[0]
    required_cols = {
        "provider_code",
        "external_sale_id",
        "sold_at",
        "fridge_external_id",
        "product_sku",
        "quantity",
        "unit_price",
        "total_amount",
        "payment_status",
        "receipt_number",
    }
    header_cols = set(header.split(","))
    assert required_cols.issubset(header_cols), f"Пропущены колонки: {required_cols - header_cols}"
    assert len(lines) > 1, "CSV не содержит строк данных"


@pytest.mark.django_db
def test_demo_csv_has_valid_provider_code():
    """Все строки демо-CSV используют provider_code=DEMO."""
    from pathlib import Path

    from django.conf import settings

    csv_path = Path(settings.BASE_DIR) / DEMO_SALES_CSV
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    for line in lines[1:]:
        if line.strip():
            provider_code = line.split(",")[0]
            assert provider_code == "DEMO", f"Неожиданный provider_code: {provider_code}"


@pytest.mark.django_db
def test_demo_csv_fridge_ids_match_seed():
    """Fridge IDs в demo_sales.csv соответствуют F-001..F-007 из seed_demo."""
    from pathlib import Path

    from django.conf import settings

    csv_path = Path(settings.BASE_DIR) / DEMO_SALES_CSV
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    valid_ids = {f"F-{i:03d}" for i in range(1, 8)}
    for line in lines[1:]:
        if line.strip():
            parts = line.split(",")
            fridge_id = parts[3]
            assert fridge_id in valid_ids, f"Неизвестный fridge_id: {fridge_id}"


@pytest.mark.django_db
def test_demo_csv_product_skus_match_seed():
    """SKU в demo_sales.csv соответствуют товарам из seed_demo."""
    from pathlib import Path

    from django.conf import settings

    csv_path = Path(settings.BASE_DIR) / DEMO_SALES_CSV
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    valid_skus = {
        "SAND-CHICKEN",
        "SAND-HAM",
        "SALAD-CAESAR",
        "SALAD-GREEK",
        "PASTA-BOLOGNESE",
        "RICE-CHICKEN",
        "DESSERT-CHEESE",
        "WATER-05",
        "COLA-05",
        "BAR-NUT",
    }
    for line in lines[1:]:
        if line.strip():
            parts = line.split(",")
            sku = parts[4]
            assert sku in valid_skus, f"Неизвестный SKU: {sku}"
