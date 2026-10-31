import csv
import hashlib
import io
import math
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (
    Batch,
    Forecast,
    Fridge,
    ImportJob,
    InventoryMovement,
    Product,
    Sale,
    SaleItem,
    StockLocation,
    StockTransfer,
)

REQUIRED_COLUMNS = {
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


def balance(location, product=None, batch=None):
    query = InventoryMovement.objects.filter(stock_location=location)
    if product:
        query = query.filter(product=product)
    if batch:
        query = query.filter(batch=batch)
    return query.aggregate(value=Sum("quantity"))["value"] or 0


@transaction.atomic
def post_transfer(transfer: StockTransfer):
    transfer = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
    if transfer.status != StockTransfer.Status.DRAFT:
        raise ValueError("Можно провести только черновик перемещения.")
    transfer.full_clean()
    items = list(transfer.items.select_related("product", "batch"))
    if not items:
        raise ValueError("В перемещении нет товаров.")
    for item in items:
        if balance(transfer.source_location, item.product, item.batch) < item.quantity:
            raise ValueError(f"Недостаточный остаток: {item.product.sku}/{item.batch.batch_number}")
    for item in items:
        common = {
            "organization": transfer.organization,
            "product": item.product,
            "batch": item.batch,
            "transfer": transfer,
            "unit_cost": item.unit_cost,
            "occurred_at": transfer.occurred_at,
            "source_type": InventoryMovement.Source.MANUAL,
            "created_by": transfer.created_by,
        }
        InventoryMovement.objects.create(
            stock_location=transfer.source_location,
            movement_type=InventoryMovement.Type.TRANSFER_OUT,
            quantity=-item.quantity,
            **common,
        )
        InventoryMovement.objects.create(
            stock_location=transfer.destination_location,
            movement_type=InventoryMovement.Type.TRANSFER_IN,
            quantity=item.quantity,
            **common,
        )
    transfer.status = StockTransfer.Status.POSTED
    transfer.save(update_fields=["status", "updated_at"])
    return transfer


def _decode_csv(file_bytes):
    text = file_bytes.decode("utf-8-sig")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def validate_sales_csv(file_bytes, organization, provider):
    errors = []
    valid = []
    try:
        rows = _decode_csv(file_bytes)
    except (UnicodeDecodeError, csv.Error) as exc:
        return [], [{"row": 0, "error": f"Файл не читается: {exc}"}]
    if not rows:
        return [], [{"row": 0, "error": "CSV пуст."}]
    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        return [], [{"row": 1, "error": f"Нет колонок: {', '.join(sorted(missing))}"}]

    for number, raw in enumerate(rows, start=2):
        row_errors = []
        try:
            if raw["provider_code"].strip() != provider.code:
                row_errors.append("provider_code не соответствует выбранному поставщику")
            fridge = Fridge.objects.get(
                organization=organization,
                provider=provider,
                external_id=raw["fridge_external_id"].strip(),
            )
        except Fridge.DoesNotExist:
            fridge = None
            row_errors.append("неизвестный холодильник")
        try:
            product = Product.objects.get(
                organization=organization, sku=raw["product_sku"].strip(), is_active=True
            )
        except Product.DoesNotExist:
            product = None
            row_errors.append("неизвестный SKU")
        sold_at = parse_datetime(raw["sold_at"].strip())
        if sold_at is None or timezone.is_naive(sold_at):
            row_errors.append("sold_at должен быть ISO-датой с часовым поясом")
        try:
            quantity = int(raw["quantity"])
            unit_price = Decimal(raw["unit_price"].replace(",", "."))
            total_amount = Decimal(raw["total_amount"].replace(",", "."))
            if quantity <= 0 or unit_price < 0 or total_amount < 0:
                raise ValueError
            if unit_price * quantity != total_amount:
                row_errors.append("total_amount не равен quantity × unit_price")
        except (ValueError, InvalidOperation):
            quantity = 0
            unit_price = total_amount = Decimal("0")
            row_errors.append("некорректное количество или цена")
        status = raw["payment_status"].strip().upper()
        if status not in Sale.PaymentStatus.values:
            row_errors.append("неизвестный payment_status")
        external_id = raw["external_sale_id"].strip()
        if not external_id:
            row_errors.append("пустой external_sale_id")
        if row_errors:
            errors.append({"row": number, "error": "; ".join(row_errors)})
        else:
            valid.append(
                {
                    "raw": raw,
                    "fridge": fridge,
                    "product": product,
                    "sold_at": sold_at,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "total_amount": total_amount,
                    "status": status,
                    "external_id": external_id,
                }
            )
    return valid, errors


def _fefo_batch(fridge_location, product, sold_at):
    batches = Batch.objects.filter(
        organization=fridge_location.organization,
        product=product,
        status=Batch.Status.ACTIVE,
        expires_at__gt=sold_at,
    ).order_by("expires_at")
    for batch in batches:
        if balance(fridge_location, product, batch) > 0:
            return batch
    return None


@transaction.atomic
def import_sales_csv(file_bytes, filename, organization, provider, user=None):
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    previous = ImportJob.objects.filter(
        organization=organization,
        provider=provider,
        file_hash=file_hash,
        status=ImportJob.Status.COMMITTED,
    ).first()
    if previous:
        return previous, True

    valid, errors = validate_sales_csv(file_bytes, organization, provider)
    job = ImportJob.objects.create(
        organization=organization,
        provider=provider,
        filename=filename,
        file_hash=file_hash,
        status=ImportJob.Status.FAILED if errors else ImportJob.Status.VALIDATED,
        total_rows=len(valid) + len(errors),
        valid_rows=len(valid),
        error_rows=len(errors),
        error_report=errors,
        created_by=user,
    )
    if errors:
        return job, False

    grouped = defaultdict(list)
    for item in valid:
        grouped[(item["fridge"].id, item["external_id"])].append(item)

    duplicate_rows = 0
    for (_fridge_id, external_id), items in grouped.items():
        first = items[0]
        sale, created = Sale.objects.get_or_create(
            organization=organization,
            provider=provider,
            fridge=first["fridge"],
            external_id=external_id,
            defaults={
                "sold_at": first["sold_at"],
                "total_amount": sum((x["total_amount"] for x in items), Decimal("0")),
                "payment_status": first["status"],
                "receipt_number": first["raw"].get("receipt_number", ""),
                "raw_payload": {"rows": [x["raw"] for x in items]},
            },
        )
        if not created:
            duplicate_rows += len(items)
            continue
        fridge_location = StockLocation.objects.get(fridge=first["fridge"])
        for item in items:
            batch = _fefo_batch(fridge_location, item["product"], item["sold_at"])
            SaleItem.objects.create(
                sale=sale,
                product=item["product"],
                batch=batch,
                batch_allocation_source=(
                    SaleItem.Allocation.ESTIMATED_FEFO if batch else SaleItem.Allocation.UNKNOWN
                ),
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                unit_cost=item["product"].cost_price,
            )
            if batch:
                InventoryMovement.objects.create(
                    organization=organization,
                    stock_location=fridge_location,
                    product=item["product"],
                    batch=batch,
                    movement_type=InventoryMovement.Type.SALE,
                    quantity=-item["quantity"],
                    unit_cost=item["product"].cost_price,
                    occurred_at=item["sold_at"],
                    source_type=InventoryMovement.Source.CSV,
                    external_id=f"{provider.code}:{first['fridge'].external_id}:{external_id}:{item['product'].sku}",
                    created_by=user,
                    metadata={"batch_is_estimated": True},
                )

    job.status = ImportJob.Status.COMMITTED
    job.duplicate_rows = duplicate_rows
    job.committed_at = timezone.now()
    job.save(update_fields=["status", "duplicate_rows", "committed_at", "updated_at"])
    return job, False


def generate_forecasts(organization, target_date=None, safety_stock=Decimal("0.15"), horizon_days=2):
    """Строит рекомендации к пополнению по продажам и текущему остатку.

    ``horizon_days`` — сколько дней витрина должна быть закрыта запасом. Витрины
    обслуживаются несколько раз в неделю, поэтому целевой запас считается как
    спрос за ``horizon_days`` с запасом прочности, а не за один день: иначе
    рекомендация получилась бы одинаковой для всех позиций.
    """
    target_date = target_date or (timezone.localdate() + timedelta(days=1))
    today = timezone.localdate()
    since_28 = timezone.now() - timedelta(days=28)
    since_14 = timezone.now() - timedelta(days=14)
    horizon = Decimal(str(horizon_days))
    created = []
    for fridge in Fridge.objects.filter(organization=organization, status=Fridge.Status.ACTIVE):
        location = StockLocation.objects.get(fridge=fridge)
        for product in Product.objects.filter(organization=organization, is_active=True):
            items = SaleItem.objects.filter(
                sale__fridge=fridge,
                sale__sold_at__gte=since_28,
                sale__payment_status=Sale.PaymentStatus.PAID,
                product=product,
            ).select_related("sale")
            same_weekday_total = sum(
                x.quantity
                for x in items
                if x.sale.sold_at.astimezone().weekday() == target_date.weekday()
            )
            same_weekday_days = max(
                1,
                sum(
                    1
                    for i in range(28)
                    if (today - timedelta(days=i)).weekday() == target_date.weekday()
                ),
            )
            same_weekday_avg = Decimal(same_weekday_total) / Decimal(same_weekday_days)
            last_14_total = sum(x.quantity for x in items if x.sale.sold_at >= since_14)
            last_14_avg = Decimal(last_14_total) / Decimal("14")
            daily_demand = Decimal("0.6") * same_weekday_avg + Decimal("0.4") * last_14_avg
            predicted = math.ceil(daily_demand)
            usable_stock = balance(location, product)
            target_stock = math.ceil(daily_demand * horizon * (Decimal("1") + safety_stock))
            replenish = max(0, target_stock - usable_stock)
            forecast, _ = Forecast.objects.update_or_create(
                organization=organization,
                fridge=fridge,
                product=product,
                forecast_date=target_date,
                model_version="weighted-v1",
                defaults={
                    "predicted_quantity": predicted,
                    "replenish_quantity": replenish,
                    "explanation": {
                        "same_weekday_average": str(same_weekday_avg.quantize(Decimal("0.01"))),
                        "last_14_days_average": str(last_14_avg.quantize(Decimal("0.01"))),
                        "usable_stock": usable_stock,
                        "safety_stock": str(safety_stock),
                        "horizon_days": horizon_days,
                    },
                },
            )
            if replenish > 0:
                created.append(forecast)
    return created
