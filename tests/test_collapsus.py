"""Проверка устойчивости к сбоям: атомарность импорта, целостность перемещений."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import (
    Batch,
    DeviceProvider,
    Fridge,
    ImportJob,
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
from core.services import balance, import_sales_csv, post_transfer


@pytest.fixture
def setup_org(db):
    org = Organization.objects.create(name="Тест-коллапсус")
    user = User.objects.create_user("testuser", password="pass")
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    provider = DeviceProvider.objects.create(organization=org, code="COLL", name="Collapse")
    point = Location.objects.create(organization=org, name="Точка", address="Адрес")
    fridge = Fridge.objects.create(
        organization=org,
        location=point,
        provider=provider,
        name="Холод",
        serial_number="S1",
        external_id="F1",
    )
    warehouse = StockLocation.objects.create(
        organization=org, type=StockLocation.Type.WAREHOUSE, name="Склад"
    )
    fridge_loc = StockLocation.objects.create(
        organization=org, type=StockLocation.Type.FRIDGE, name="Витрина", fridge=fridge
    )
    product = Product.objects.create(
        organization=org,
        sku="TEST-SKU",
        name="Тест",
        cost_price=Decimal("100"),
        sale_price=Decimal("200"),
    )
    batch = Batch.objects.create(
        organization=org,
        product=product,
        batch_number="B-COLL",
        expires_at=timezone.now() + timedelta(days=5),
    )
    InventoryMovement.objects.create(
        organization=org,
        stock_location=warehouse,
        product=product,
        batch=batch,
        movement_type=InventoryMovement.Type.INITIAL,
        quantity=50,
        unit_cost=product.cost_price,
        occurred_at=timezone.now(),
        source_type=InventoryMovement.Source.SYSTEM,
    )
    InventoryMovement.objects.create(
        organization=org,
        stock_location=fridge_loc,
        product=product,
        batch=batch,
        movement_type=InventoryMovement.Type.INITIAL,
        quantity=20,
        unit_cost=product.cost_price,
        occurred_at=timezone.now(),
        source_type=InventoryMovement.Source.SYSTEM,
    )
    return org, user, provider, fridge, warehouse, fridge_loc, product, batch


@pytest.mark.django_db
def test_bad_csv_atomic_no_partial_write(setup_org):
    """CSV с одной ошибочной строкой не создаёт ни одной продажи."""
    org, user, provider, fridge, _, _, _, _ = setup_org
    now_iso = timezone.now().isoformat()
    data = (
        "provider_code,external_sale_id,sold_at,fridge_external_id,product_sku,"
        "quantity,unit_price,total_amount,payment_status,receipt_number\n"
        f"COLL,GOOD-1,{now_iso},{fridge.external_id},TEST-SKU,1,200.00,200.00,PAID,R1\n"
        f"COLL,BAD-1,{now_iso},{fridge.external_id},UNKNOWN-SKU,1,200.00,200.00,PAID,R2\n"
    ).encode()
    job, _ = import_sales_csv(data, "bad.csv", org, provider, user)
    assert job.status == ImportJob.Status.FAILED
    assert Sale.objects.filter(organization=org).count() == 0
    assert SaleItem.objects.filter(sale__organization=org).count() == 0


@pytest.mark.django_db
def test_duplicate_import_no_side_effects(setup_org):
    """Повторный импорт одного файла не создаёт дублей продаж."""
    org, user, provider, fridge, _, fridge_loc, product, batch = setup_org
    now_iso = timezone.now().isoformat()
    data = (
        "provider_code,external_sale_id,sold_at,fridge_external_id,product_sku,"
        "quantity,unit_price,total_amount,payment_status,receipt_number\n"
        f"COLL,DUP-1,{now_iso},{fridge.external_id},TEST-SKU,1,200.00,200.00,PAID,R1\n"
    ).encode()
    job1, _ = import_sales_csv(data, "sales.csv", org, provider, user)
    balance_after_first = balance(fridge_loc, product, batch)
    job2, repeated = import_sales_csv(data, "sales.csv", org, provider, user)
    assert repeated is True
    assert Sale.objects.filter(organization=org).count() == 1
    assert balance(fridge_loc, product, batch) == balance_after_first


@pytest.mark.django_db
def test_transfer_insufficient_stock_atomic(setup_org):
    """Перемещение с недостаточным остатком не создаёт движений."""
    org, user, _, _, warehouse, fridge_loc, product, batch = setup_org
    transfer = StockTransfer.objects.create(
        organization=org,
        source_location=warehouse,
        destination_location=fridge_loc,
        occurred_at=timezone.now(),
        created_by=user,
    )
    StockTransferItem.objects.create(
        transfer=transfer, product=product, batch=batch, quantity=999, unit_cost=Decimal("100")
    )
    with pytest.raises(ValueError, match="Недостаточный остаток"):
        post_transfer(transfer)
    assert InventoryMovement.objects.filter(transfer=transfer).count() == 0
    assert balance(warehouse, product, batch) == 50


@pytest.mark.django_db
def test_transfer_posted_cannot_repost(setup_org):
    """Проведённое перемещение нельзя провести повторно."""
    org, user, _, _, warehouse, fridge_loc, product, batch = setup_org
    transfer = StockTransfer.objects.create(
        organization=org,
        source_location=warehouse,
        destination_location=fridge_loc,
        occurred_at=timezone.now(),
        created_by=user,
    )
    StockTransferItem.objects.create(
        transfer=transfer, product=product, batch=batch, quantity=5, unit_cost=Decimal("100")
    )
    post_transfer(transfer)
    with pytest.raises(ValueError, match="только черновик"):
        post_transfer(transfer)
    assert InventoryMovement.objects.filter(transfer=transfer).count() == 2


@pytest.mark.django_db
def test_empty_csv_fails_gracefully(setup_org):
    """Пустой CSV не падает, а возвращает ошибку."""
    org, user, provider, _, _, _, _, _ = setup_org
    data = b""
    job, _ = import_sales_csv(data, "empty.csv", org, provider, user)
    assert job.status == ImportJob.Status.FAILED
    assert Sale.objects.filter(organization=org).count() == 0


@pytest.mark.django_db
def test_missing_columns_csv_fails(setup_org):
    """CSV без обязательных колонок отклоняется атомарно."""
    org, user, provider, _, _, _, _, _ = setup_org
    data = b"col1,col2\nval1,val2\n"
    job, _ = import_sales_csv(data, "nocols.csv", org, provider, user)
    assert job.status == ImportJob.Status.FAILED
    assert Sale.objects.filter(organization=org).count() == 0


@pytest.mark.django_db
def test_sale_total_mismatch_rejected(setup_org):
    """Строка с total_amount != quantity*unit_price отклоняется."""
    org, user, provider, fridge, _, _, _, _ = setup_org
    now_iso = timezone.now().isoformat()
    data = (
        "provider_code,external_sale_id,sold_at,fridge_external_id,product_sku,"
        "quantity,unit_price,total_amount,payment_status,receipt_number\n"
        f"COLL,MISMATCH-1,{now_iso},{fridge.external_id},TEST-SKU,2,200.00,500.00,PAID,R1\n"
    ).encode()
    job, _ = import_sales_csv(data, "mismatch.csv", org, provider, user)
    assert job.status == ImportJob.Status.FAILED
    assert Sale.objects.filter(organization=org).count() == 0
