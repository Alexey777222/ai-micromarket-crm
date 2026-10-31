import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, F, Sum
from django.utils import timezone

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
from core.services import generate_forecasts

DEMO_ORG_NAME = "Демо-сеть микромаркетов"
DEMO_PROVIDER_CODE = "DEMO"
DEMO_PROVIDER_NAME = "Демонстрационная выгрузка оборудования"
DEMO_USER = "demo"
DEMO_PASSWORD = "demo12345"

# Глубина синтетической истории продаж.
HISTORY_DAYS = 60
# Число продаж в истории по техническому заданию: ровно 4100 записей
# с идентификаторами SYNTH-000001..SYNTH-004100.
SALES_COUNT = 4100
# Точное распределение статусов оплаты по заданию (4059 + 25 + 16 = 4100).
CANCELLED_SALES_COUNT = 25
REFUNDED_SALES_COUNT = 16
# Целевая доля списаний от выручки за 30 дней.
WRITE_OFF_RATIO = Decimal("0.065")
# Суммарный остаток холодильника по всем товарам.
FRIDGE_STOCK_RANGE = (92, 118)
# Товары с таким сроком хранения и короче считаются скоропортящимися.
FRESH_SHELF_LIMIT_HOURS = 120
# Максимальная длина периода оборота одной партии (для товаров с длинным сроком).
MAX_BATCH_PERIOD_DAYS = 14
# Товар на витрине считается «на исходе», если остаток не больше этого значения.
LOW_STOCK_THRESHOLD = 3

FRIDGE_CONFIG = [
    {
        "external_id": "F-001",
        "name": "Холодильник 1 — БЦ Север",
        "serial_number": "RF450-0001",
        "model": "Smart Market RF-450",
        "demand_coefficient": Decimal("1.30"),
        "address": "Москва, демонстрационный адрес: пр. Мира, 1, корп. 1 (демо-адрес)",
    },
    {
        "external_id": "F-002",
        "name": "Холодильник 2 — БЦ Центр",
        "serial_number": "RF450-0002",
        "model": "Smart Market RF-450",
        "demand_coefficient": Decimal("1.20"),
        "address": "Москва, демонстрационный адрес: ул. Лесная, 12, стр. 3 (демо-адрес)",
    },
    {
        "external_id": "F-003",
        "name": "Холодильник 3 — Коворкинг",
        "serial_number": "RF450-0003",
        "model": "Smart Market RF-450",
        "demand_coefficient": Decimal("0.85"),
        "address": "Москва, демонстрационный адрес: ул. Техническая, 7, оф. 21 (демо-адрес)",
    },
    {
        "external_id": "F-004",
        "name": "Холодильник 4 — Технопарк",
        "serial_number": "RF450-0004",
        "model": "Smart Market RF-450",
        "demand_coefficient": Decimal("1.10"),
        "address": "Москва, демонстрационный адрес: пр. Ильича, 25, пав. 4 (демо-адрес)",
    },
    {
        "external_id": "F-005",
        "name": "Холодильник 5 — Фитнес-центр",
        "serial_number": "RF450-0005",
        "model": "Smart Market RF-450",
        "demand_coefficient": Decimal("0.80"),
        "address": "Москва, демонстрационный адрес: ул. Спортивная, 88, вход Б (демо-адрес)",
    },
    {
        "external_id": "F-006",
        "name": "Холодильник 6 — Офисный центр",
        "serial_number": "RF450-0006",
        "model": "Smart Market RF-450",
        "demand_coefficient": Decimal("0.70"),
        "address": "Москва, демонстрационный адрес: ул. Кадровая, 9, этаж 4 (демо-адрес)",
    },
    {
        "external_id": "F-007",
        "name": "Холодильник 7 — БЦ Запад",
        "serial_number": "RF450-0007",
        "model": "Smart Market RF-450",
        "demand_coefficient": Decimal("1.05"),
        "address": "Москва, демонстрационный адрес: пр. Славы, 14, блок А (демо-адрес)",
    },
]

PRODUCT_SPECS = [
    {
        "sku": "SAND-CHICKEN",
        "name": "Сэндвич с курицей",
        "category": "Сэндвичи",
        "barcode": "2000000000015",
        "cost_price": Decimal("118.00"),
        "sale_price": Decimal("259.00"),
        "shelf_life_hours": 72,
    },
    {
        "sku": "SAND-HAM",
        "name": "Сэндвич с ветчиной",
        "category": "Сэндвичи",
        "barcode": "2000000000022",
        "cost_price": Decimal("112.00"),
        "sale_price": Decimal("249.00"),
        "shelf_life_hours": 72,
    },
    {
        "sku": "SALAD-CAESAR",
        "name": "Салат Цезарь",
        "category": "Салаты",
        "barcode": "2000000000039",
        "cost_price": Decimal("145.00"),
        "sale_price": Decimal("329.00"),
        "shelf_life_hours": 48,
    },
    {
        "sku": "SALAD-GREEK",
        "name": "Салат Греческий",
        "category": "Салаты",
        "barcode": "2000000000046",
        "cost_price": Decimal("132.00"),
        "sale_price": Decimal("299.00"),
        "shelf_life_hours": 48,
    },
    {
        "sku": "PASTA-BOLOGNESE",
        "name": "Паста Болоньезе",
        "category": "Горячие блюда",
        "barcode": "2000000000053",
        "cost_price": Decimal("165.00"),
        "sale_price": Decimal("379.00"),
        "shelf_life_hours": 72,
    },
    {
        "sku": "RICE-CHICKEN",
        "name": "Рис с курицей",
        "category": "Горячие блюда",
        "barcode": "2000000000060",
        "cost_price": Decimal("155.00"),
        "sale_price": Decimal("359.00"),
        "shelf_life_hours": 72,
    },
    {
        "sku": "DESSERT-CHEESE",
        "name": "Чизкейк",
        "category": "Десерты",
        "barcode": "2000000000077",
        "cost_price": Decimal("92.00"),
        "sale_price": Decimal("219.00"),
        "shelf_life_hours": 96,
    },
    {
        "sku": "WATER-05",
        "name": "Вода 0,5 л",
        "category": "Напитки",
        "barcode": "2000000000084",
        "cost_price": Decimal("28.00"),
        "sale_price": Decimal("79.00"),
        "shelf_life_hours": 4320,
    },
    {
        "sku": "COLA-05",
        "name": "Кола 0,5 л",
        "category": "Напитки",
        "barcode": "2000000000091",
        "cost_price": Decimal("52.00"),
        "sale_price": Decimal("129.00"),
        "shelf_life_hours": 4320,
    },
    {
        "sku": "BAR-NUT",
        "name": "Ореховый батончик",
        "category": "Снеки",
        "barcode": "2000000000107",
        "cost_price": Decimal("43.00"),
        "sale_price": Decimal("119.00"),
        "shelf_life_hours": 2160,
    },
]

PRODUCT_WEIGHTS = [
    ("SAND-CHICKEN", 0.17),
    ("SAND-HAM", 0.14),
    ("SALAD-CAESAR", 0.10),
    ("SALAD-GREEK", 0.09),
    ("PASTA-BOLOGNESE", 0.15),
    ("RICE-CHICKEN", 0.12),
    ("DESSERT-CHEESE", 0.06),
    ("WATER-05", 0.12),
    ("COLA-05", 0.10),
    ("BAR-NUT", 0.05),
]

DAY_WEIGHTS = {
    0: 1.35,
    1: 1.20,
    2: 1.45,
    3: 1.25,
    4: 1.50,
    5: 0.60,
    6: 0.45,
}

# Доли числа позиций в чеке: микромаркет — это преимущественно одна позиция.
ITEM_COUNT_ROLLOFFS = [(0.60, 1), (0.90, 2), (1.01, 3)]

# Часы работы витрины, из них выбирается время продажи.
SALE_HOURS = [9, 9, 10, 10, 11, 12, 12, 13, 13, 14, 14, 15]
SALE_MINUTES = [0, 5, 10, 15, 20, 30, 40, 45, 50]
# Время утренней поставки на витрину.
DELIVERY_HOUR = 6


class Command(BaseCommand):
    help = "Создаёт расширенный демонстрационный набор данных для владельца микромаркетов."

    def add_arguments(self, parser):
        parser.add_argument("--replace", action="store_true", help="Пересоздать только синтетические данные.")

    # ------------------------------------------------------------------
    # Собственная синтетика: обнаружение и очистка
    # ------------------------------------------------------------------
    def _has_synthetic_demo_data(self, organization):
        return any(
            [
                Sale.objects.filter(organization=organization, external_id__startswith="SYNTH-").exists(),
                InventoryMovement.objects.filter(organization=organization, external_id__startswith="SYNTH:").exists(),
                Batch.objects.filter(organization=organization, batch_number__startswith="SYNTH-BATCH-").exists(),
                StockTransfer.objects.filter(organization=organization, external_id__startswith="SYNTH-TRANSFER-").exists(),
                Forecast.objects.filter(
                    organization=organization, explanation__demo_source="business_demo"
                ).exists(),
                Alert.objects.filter(organization=organization, message__startswith="Демо:").exists(),
            ]
        )

    def _delete_synthetic_demo_data(self, organization):
        Sale.objects.filter(organization=organization, external_id__startswith="SYNTH-").delete()
        InventoryMovement.objects.filter(organization=organization, external_id__startswith="SYNTH:").delete()
        InventoryMovement.objects.filter(
            organization=organization,
            transfer__external_id__startswith="SYNTH-TRANSFER-",
        ).delete()
        StockTransferItem.objects.filter(
            transfer__organization=organization,
            transfer__external_id__startswith="SYNTH-TRANSFER-",
        ).delete()
        StockTransfer.objects.filter(organization=organization, external_id__startswith="SYNTH-TRANSFER-").delete()
        Batch.objects.filter(organization=organization, batch_number__startswith="SYNTH-BATCH-").delete()
        # Прогнозы демо-организации пересоздаются целиком: разные версии модели
        # на одну дату дублировали пары «холодильник + товар» на дашборде.
        Forecast.objects.filter(organization=organization).delete()
        Alert.objects.filter(organization=organization, message__startswith="Демо:").delete()

    def _purge_standard_demo_sales(self, organization):
        """Удаляет продажи демонстрационного CSV-импорта стандартного набора.

        Инструкция пилота (``START_HERE``) предлагает загрузить
        ``samples/demo_sales.csv`` через демо-провайдера. Вместе с расширенным
        набором эти продажи остаются в организации, и в административной панели
        оказывается больше записей, чем задано (4100 синтетических).

        Границы удаления:

        * только демонстрационная организация и только её демо-провайдер
          (код ``DEMO``) — продажи других организаций и провайдеров не затрагиваются;
        * продажи расширенного набора (``SYNTH-``) не затрагиваются;
        * движения продаж демо-импорта помечены префиксом ``DEMO:`` и удаляются
          вместе с ними, иначе они искажают остатки витрин.
        """
        sales = Sale.objects.filter(
            organization=organization,
            provider__code=DEMO_PROVIDER_CODE,
        ).exclude(external_id__startswith="SYNTH-")
        count = sales.count()
        if count:
            InventoryMovement.objects.filter(
                organization=organization,
                movement_type=InventoryMovement.Type.SALE,
                external_id__startswith=f"{DEMO_PROVIDER_CODE}:",
            ).delete()
            sales.delete()
        return count

    def _purge_standard_demo_batches(self, organization):
        """Убирает влияние партий стандартного ``seed_demo`` на демо-витрину.

        Расширенный набор описывает витрину собственными партиями ``SYNTH-BATCH-*``.
        Стартовое наполнение ``DEMO-*`` остаётся в той же организации и портило
        остатки, блок «истекает в течение 48 часов» и рекомендации.

        Правила, ограничивающие удаление пользовательскими данными:

        * выборка ограничена ``organization`` — другие организации не затрагиваются;
        * партия и её движения удаляются целиком, если это только наполнение
          ``seed_demo`` (движения без внешнего идентификатора) и на партию не
          ссылаются продажи или перемещения;
        * если партию используют продажи или перемещения, данные сохраняются:
          партия переводится в ``EXPIRED`` и её остатки на витринах обнуляются
          инвентаризационной корректировкой. Так она больше не попадает в сроки
          годности, остатки и рекомендации.
        """
        removed = 0
        neutralized = 0
        for batch in Batch.objects.filter(organization=organization, batch_number__startswith="DEMO-"):
            movements = InventoryMovement.objects.filter(batch=batch)
            seed_only_movements = not movements.exclude(
                source_type=InventoryMovement.Source.SYSTEM, external_id=""
            ).exists()
            has_document_refs = (
                SaleItem.objects.filter(batch=batch).exists()
                or StockTransferItem.objects.filter(batch=batch)
                .exclude(transfer__external_id__startswith="SYNTH-TRANSFER-")
                .exists()
            )
            if seed_only_movements and not has_document_refs:
                movements.delete()
                batch.delete()
                removed += 1
                continue

            for row in (
                movements.filter(stock_location__type=StockLocation.Type.FRIDGE)
                .values("stock_location")
                .annotate(total=Sum("quantity"))
            ):
                if (row["total"] or 0) > 0:
                    InventoryMovement.objects.create(
                        organization=organization,
                        stock_location_id=row["stock_location"],
                        product=batch.product,
                        batch=batch,
                        movement_type=InventoryMovement.Type.INVENTORY_ADJUSTMENT,
                        quantity=-row["total"],
                        unit_cost=batch.purchase_cost or batch.product.cost_price,
                        occurred_at=timezone.now(),
                        source_type=InventoryMovement.Source.SYSTEM,
                        external_id=f"SYNTH:NEUTRALIZE:{batch.batch_number}",
                        reason="Сторонняя партия снята с витрины при сборке демо-набора",
                        metadata={"demo": True},
                    )
            if batch.status != Batch.Status.EXPIRED:
                batch.status = Batch.Status.EXPIRED
                batch.save(update_fields=["status", "updated_at"])
            neutralized += 1

        return removed, neutralized

    # ------------------------------------------------------------------
    # Справочники
    # ------------------------------------------------------------------
    def _ensure_default_demo_data(self):
        call_command("seed_demo")
        organization = Organization.objects.get(name=DEMO_ORG_NAME)
        user, _ = User.objects.get_or_create(username=DEMO_USER, defaults={"email": "demo@example.com"})
        if settings.IS_PRODUCTION:
            user.set_unusable_password()
            user.is_active = False
            user.is_staff = False
            user.is_superuser = False
        else:
            user.set_password(DEMO_PASSWORD)
            user.is_staff = True
            user.is_superuser = True
        user.save()
        Membership.objects.get_or_create(
            organization=organization,
            user=user,
            defaults={"role": Membership.Role.OWNER},
        )
        return organization

    def _ensure_provider(self, organization):
        provider, _ = DeviceProvider.objects.update_or_create(
            organization=organization,
            code=DEMO_PROVIDER_CODE,
            defaults={"name": DEMO_PROVIDER_NAME, "adapter_type": "canonical_csv", "is_active": True},
        )
        return provider

    def _ensure_fridges(self, organization, provider):
        fridges = {}
        for config in FRIDGE_CONFIG:
            location, _ = Location.objects.update_or_create(
                organization=organization,
                name=f"Демо-площадка {config['external_id']}",
                defaults={
                    "address": config["address"],
                    "working_hours": "08:00-20:00",
                    "visit_days": "понедельник, среда, пятница",
                    "is_active": True,
                },
            )
            fridge, _ = Fridge.objects.update_or_create(
                organization=organization,
                provider=provider,
                external_id=config["external_id"],
                defaults={
                    "location": location,
                    "name": config["name"],
                    "serial_number": config["serial_number"],
                    "model": config["model"],
                    "status": Fridge.Status.ACTIVE,
                },
            )
            StockLocation.objects.update_or_create(
                organization=organization,
                fridge=fridge,
                defaults={"type": StockLocation.Type.FRIDGE, "name": fridge.name, "is_active": True},
            )
            fridges[config["external_id"]] = fridge
        return fridges

    def _ensure_products(self, organization):
        products = {}
        for spec in PRODUCT_SPECS:
            product, _ = Product.objects.update_or_create(
                organization=organization,
                sku=spec["sku"],
                defaults={
                    "barcode": spec["barcode"],
                    "name": spec["name"],
                    "category": spec["category"],
                    "cost_price": spec["cost_price"],
                    "sale_price": spec["sale_price"],
                    "shelf_life_hours": spec["shelf_life_hours"],
                    "is_active": True,
                },
            )
            products[spec["sku"]] = product
        return products

    # ------------------------------------------------------------------
    # Утилиты дат
    # ------------------------------------------------------------------
    @staticmethod
    def _local_dt(day, hour, minute=0):
        return timezone.make_aware(datetime.combine(day, time(hour=hour, minute=minute)))

    @staticmethod
    def _is_fresh(product):
        return (product.shelf_life_hours or 0) <= FRESH_SHELF_LIMIT_HOURS

    @classmethod
    def _period_days(cls, product):
        """Сколько дней витрина торгует одной партией товара."""
        shelf_days = max(1, (product.shelf_life_hours or 24) // 24)
        return min(shelf_days, MAX_BATCH_PERIOD_DAYS)

    # ------------------------------------------------------------------
    # Партии
    # ------------------------------------------------------------------
    def _create_batches(self, organization, products, now, today, rng):
        """Создаёт партии товара и календарь их обращения.

        На каждый товар формируется цепочка партий:

        * ``-H<k>`` — историческая партия периода ``k``; отгружается на витрину в
          начале периода, продаётся внутри него, непросроченный остаток списывается
          в конце периода;
        * ``-CUR``  — рабочая партия текущего периода, формирует остаток витрины;
        * ``-EXP``  — маленькая заканчивающаяся партия (только скоропорт). Она и
          попадает в блок «истекает в течение 48 часов».

        Срок годности каждой партии = дата производства + ``shelf_life_hours``,
        приход датируется началом периода, поэтому продажи партии всегда идут после
        прихода и остаток не может стать отрицательным.
        """
        result = {}
        for sku, product in products.items():
            period_days = self._period_days(product)
            shelf = timedelta(hours=product.shelf_life_hours or 720)
            fresh = self._is_fresh(product)
            periods = (HISTORY_DAYS - 1) // period_days + 1
            entries = {}

            for index in range(1, periods + 1):
                start_day = today - timedelta(days=index * period_days)
                produced_at = self._local_dt(start_day, DELIVERY_HOUR - 2)
                key = f"h{index:02d}"
                expires_at = produced_at + shelf
                entries[key] = {
                    "batch": Batch.objects.create(
                        organization=organization,
                        product=product,
                        batch_number=f"SYNTH-BATCH-{sku}-{key.upper()}",
                        produced_at=produced_at,
                        expires_at=expires_at,
                        supplier=DEMO_PROVIDER_NAME,
                        purchase_cost=product.cost_price,
                        # Партия отжила свой срок — статус соответствует реальному положению.
                        status=Batch.Status.EXPIRED if expires_at <= now else Batch.Status.ACTIVE,
                    ),
                    "start_day": start_day,
                    "end_day": start_day + timedelta(days=period_days),
                    "receipt_at": self._local_dt(start_day, DELIVERY_HOUR),
                }

            cur_produced = now - timedelta(hours=rng.randint(3, max(4, period_days * 6)))
            entries["cur"] = {
                "batch": Batch.objects.create(
                    organization=organization,
                    product=product,
                    batch_number=f"SYNTH-BATCH-{sku}-CUR",
                    produced_at=cur_produced,
                    expires_at=cur_produced + shelf,
                    supplier=DEMO_PROVIDER_NAME,
                    purchase_cost=product.cost_price,
                    status=Batch.Status.ACTIVE,
                ),
                "start_day": today,
                "end_day": today + timedelta(days=period_days),
                "receipt_at": min(now - timedelta(minutes=5), self._local_dt(today, DELIVERY_HOUR)),
            }

            if fresh:
                # Заканчивающаяся партия: срок годности подбираем так, чтобы он гарантированно
                # попал в окно «истекает в течение 48 часов», производство = срок - shelf_life.
                exp_expires = now + timedelta(hours=rng.randint(6, 40))
                entries["exp"] = {
                    "batch": Batch.objects.create(
                        organization=organization,
                        product=product,
                        batch_number=f"SYNTH-BATCH-{sku}-EXP",
                        produced_at=exp_expires - shelf,
                        expires_at=exp_expires,
                        supplier=DEMO_PROVIDER_NAME,
                        purchase_cost=product.cost_price,
                        status=Batch.Status.ACTIVE,
                    ),
                    "start_day": today,
                    "end_day": today + timedelta(days=period_days),
                    "receipt_at": min(now - timedelta(minutes=10), self._local_dt(today, DELIVERY_HOUR)),
                }

            result[sku] = {"fresh": fresh, "period_days": period_days, "entries": entries}
        return result

    # ------------------------------------------------------------------
    # План текущих остатков
    # ------------------------------------------------------------------
    def _plan_fridge_stock(self, rng, skus):
        """Формирует неровный план остатков одного холодильника.

        Часть позиций почти закончилась — они дадут разные количества пополнения.
        Часть стоит с запасом — пополнение им не требуется. Сумма по холодильнику
        гарантированно попадает в ``FRIDGE_STOCK_RANGE``.
        """
        target_sum = rng.randint(*FRIDGE_STOCK_RANGE)
        weights = dict(PRODUCT_WEIGHTS)
        demand_order = sorted(skus, key=lambda sku: weights.get(sku, 0.0), reverse=True)

        plan = {}
        for sku in skus:
            roll = rng.random()
            if roll < 0.32:
                plan[sku] = rng.randint(0, 3)
            elif roll < 0.72:
                plan[sku] = rng.randint(6, 13)
            else:
                plan[sku] = rng.randint(15, 26)

        # Гарантируем и позиции «на исходе», и позиции с запасом.
        low_count = sum(1 for value in plan.values() if value <= LOW_STOCK_THRESHOLD)
        for sku in demand_order[: max(0, 2 - low_count)]:
            plan[sku] = rng.randint(0, LOW_STOCK_THRESHOLD)
        high_count = sum(1 for value in plan.values() if value >= 14)
        for sku in demand_order[-3:][: max(0, 2 - high_count)]:
            plan[sku] = max(plan[sku], rng.randint(14, 24))

        factor = target_sum / (sum(plan.values()) or 1)
        plan = {sku: max(0, int(round(value * factor))) for sku, value in plan.items()}
        residual = target_sum - sum(plan.values())
        if residual:
            biggest = max(plan, key=lambda sku: plan[sku])
            plan[biggest] = max(0, plan[biggest] + residual)
        return plan

    # ------------------------------------------------------------------
    # История продаж
    # ------------------------------------------------------------------
    def _pick_sku(self, rng):
        total = sum(weight for _, weight in PRODUCT_WEIGHTS)
        threshold = rng.random() * total
        current = 0.0
        for sku, weight in PRODUCT_WEIGHTS:
            current += weight
            if threshold <= current:
                return sku
        return PRODUCT_WEIGHTS[-1][0]

    def _pick_item_count(self, rng):
        roll = rng.random()
        for limit, count in ITEM_COUNT_ROLLOFFS:
            if roll < limit:
                return count
        return 3

    def _batch_key_for(self, sku, sold_on, today, batches):
        """Возвращает ключ партии, из которой товар продавался на дату ``sold_on``."""
        period_days = batches[sku]["period_days"]
        days_ago = (today - sold_on).days
        if days_ago <= 0:
            return "cur"
        key = f"h{(days_ago - 1) // period_days + 1:02d}"
        return key if key in batches[sku]["entries"] else "cur"

    def _create_sales_history(self, organization, provider, fridges, products, batches, now, today, rng):
        """Генерирует продажи так, чтобы выручка и себестоимость сходились до копейки.

        Правила, без которых ломалась валовая маржа:

        * ``SaleItem.unit_cost`` всегда заполнен и равен ``Product.cost_price``;
        * ``Sale.total_amount`` — ровно сумма ``unit_price * quantity`` его позиций.
          Искусственный «средний чек ~395 ₽» убран: он завышал выручку относительно
          фактической себестоимости и давал невозможную маржу 82%;
        * каждая позиция берётся из партии, пришедшей до даты продажи, поэтому
          продажи обеспечиваются складским остатком;
        * статусы оплаты назначаются точно по заданию: 4059 PAID, 25 CANCELLED,
          16 REFUNDED — детерминированная выборка индексов, а не вероятности.
        """
        locations = {
            fridge.external_id: StockLocation.objects.get(organization=organization, fridge=fridge)
            for fridge in fridges.values()
        }

        # Детерминированно выбираем, какие продажи будут неоплаченными.
        non_paid_indices = rng.sample(
            range(1, SALES_COUNT + 1), CANCELLED_SALES_COUNT + REFUNDED_SALES_COUNT
        )
        cancelled_indices = set(non_paid_indices[:CANCELLED_SALES_COUNT])
        refunded_indices = set(non_paid_indices[CANCELLED_SALES_COUNT:])

        sales_to_create = []
        items_to_create = []
        movements_to_create = []
        sold_units = {}

        for index in range(1, SALES_COUNT + 1):
            sale_date = today - timedelta(days=rng.randint(0, HISTORY_DAYS - 1))
            sale_dt = self._local_dt(sale_date, rng.choice(SALE_HOURS), rng.choice(SALE_MINUTES))
            if sale_dt > now:
                # Не создаём продажи из будущего.
                sale_dt -= timedelta(days=1)
                sale_date = sale_dt.date()

            weekday_weight = Decimal(str(DAY_WEIGHTS[sale_dt.weekday()]))
            weights = [config["demand_coefficient"] * weekday_weight for config in FRIDGE_CONFIG]
            selection = rng.random() * float(sum(weights))
            accumulated = 0.0
            chosen = FRIDGE_CONFIG[-1]
            for config, weight in zip(FRIDGE_CONFIG, weights):
                accumulated += float(weight)
                if selection <= accumulated:
                    chosen = config
                    break
            fridge = fridges[chosen["external_id"]]
            location = locations[fridge.external_id]

            payment_status = Sale.PaymentStatus.PAID
            if index in cancelled_indices:
                payment_status = Sale.PaymentStatus.CANCELLED
            elif index in refunded_indices:
                payment_status = Sale.PaymentStatus.REFUNDED

            sale = Sale(
                organization=organization,
                provider=provider,
                fridge=fridge,
                external_id=f"SYNTH-{index:06d}",
                sold_at=sale_dt,
                total_amount=Decimal("0.00"),
                payment_status=payment_status,
                receipt_number=f"DEMO-R-{index:06d}",
                raw_payload={"demo": True, "source": "seed_business_demo"},
            )

            sale_total = Decimal("0.00")
            for _ in range(self._pick_item_count(rng)):
                product = products[self._pick_sku(rng)]
                # Две единицы в позиции — редкость: иначе средний чек ~436 ₽
                # выводит выручку 4100 продаж за пределы целевых 1,55–1,75 млн ₽.
                quantity = 1 if rng.random() < 0.93 else 2
                unit_cost = product.cost_price
                if unit_cost <= 0:
                    # Позиция без себестоимости исказила бы валовую прибыль.
                    continue
                batch_key = self._batch_key_for(product.sku, sale_dt.date(), today, batches)
                batch = batches[product.sku]["entries"][batch_key]["batch"]
                unit_price = product.sale_price

                items_to_create.append(
                    SaleItem(
                        sale=sale,
                        product=product,
                        batch=batch,
                        batch_allocation_source=SaleItem.Allocation.ACTUAL,
                        quantity=quantity,
                        unit_price=unit_price,
                        unit_cost=unit_cost,
                        discount_amount=Decimal("0.00"),
                    )
                )
                movements_to_create.append(
                    InventoryMovement(
                        organization=organization,
                        stock_location=location,
                        product=product,
                        batch=batch,
                        movement_type=InventoryMovement.Type.SALE,
                        quantity=-quantity,
                        unit_cost=unit_cost,
                        occurred_at=sale_dt,
                        source_type=InventoryMovement.Source.DEVICE_API,
                        external_id=f"SYNTH:SALE:{fridge.external_id}:{sale.external_id}:{product.sku}",
                        reason="Демонстрационная продажа",
                        metadata={"demo": True},
                    )
                )
                key = (fridge.external_id, product.sku, batch_key)
                sold_units[key] = sold_units.get(key, 0) + quantity
                sale_total += unit_price * Decimal(quantity)

            sale.total_amount = sale_total.quantize(Decimal("0.01"))
            sales_to_create.append(sale)

        Sale.objects.bulk_create(sales_to_create)
        SaleItem.objects.bulk_create(items_to_create)
        InventoryMovement.objects.bulk_create(movements_to_create)
        return sold_units

    # ------------------------------------------------------------------
    # Списания
    # ------------------------------------------------------------------
    def _create_write_offs(self, organization, fridges, products, batches, sold_units, today, rng):
        """Списывает просрочку до целевой доли от выручки за 30 дней.

        Списания берутся из исторических партий последних 30 дней и ограничены
        долей от продаж партии, поэтому остатки витрины не уходят в минус.
        """
        last_30 = timezone.now() - timedelta(days=30)
        revenue_30 = (
            Sale.objects.filter(
                organization=organization,
                payment_status=Sale.PaymentStatus.PAID,
                sold_at__gte=last_30,
                external_id__startswith="SYNTH-",
            ).aggregate(total=Sum("total_amount"))["total"]
            or Decimal("0")
        )
        target_total = revenue_30 * WRITE_OFF_RATIO
        locations = {
            external_id: StockLocation.objects.get(organization=organization, fridge=fridge)
            for external_id, fridge in fridges.items()
        }

        candidates = []
        for (external_id, sku, batch_key), units in sold_units.items():
            if batch_key == "cur" or units <= 0:
                continue
            entry = batches[sku]["entries"].get(batch_key)
            # Берём только периоды, целиком попадающие в окно последних 30 дней.
            if entry is None or entry["end_day"] < today - timedelta(days=29):
                continue
            candidates.append([external_id, sku, batch_key, units, entry, 0])
        rng.shuffle(candidates)

        write_off_units = {}
        write_off_total = Decimal("0")
        movements = []
        for round_index in range(3):
            if write_off_total >= target_total:
                break
            for candidate in candidates:
                if write_off_total >= target_total:
                    break
                external_id, sku, batch_key, units, entry, already = candidate
                product = products[sku]
                cap = max(1, round(units * (0.35 + 0.15 * round_index)))
                quantity = min(cap, rng.randint(1, 4)) - already
                if quantity <= 0:
                    continue
                cost = product.cost_price * Decimal(quantity)
                if write_off_total + cost > target_total * Decimal("1.03"):
                    continue
                occurred_day = entry["end_day"] - timedelta(days=1)
                movements.append(
                    InventoryMovement(
                        organization=organization,
                        stock_location=locations[external_id],
                        product=product,
                        batch=entry["batch"],
                        movement_type=InventoryMovement.Type.WRITE_OFF,
                        quantity=-quantity,
                        unit_cost=product.cost_price,
                        occurred_at=self._local_dt(occurred_day, rng.randint(16, 20)),
                        source_type=InventoryMovement.Source.SYSTEM,
                        external_id=f"SYNTH:WRITE_OFF:{external_id}:{sku}:{batch_key}:{round_index}",
                        reason="Истечение срока годности — демонстрационные данные",
                        metadata={"demo": True},
                    )
                )
                candidate[5] = already + quantity
                key = (external_id, sku, batch_key)
                write_off_units[key] = write_off_units.get(key, 0) + quantity
                write_off_total += cost

        InventoryMovement.objects.bulk_create(movements)
        return write_off_units, write_off_total

    # ------------------------------------------------------------------
    # Поставки на витрины и склад
    # ------------------------------------------------------------------
    def _create_receipts(self, organization, fridges, products, batches, sold_units, write_off_units, stock_plan, now, rng):
        """Создаёт приходы на витрины и склад.

        Количество по каждой партии = «продано + списано + оставляемый остаток»,
        приход датируется началом периода партии. Поэтому итоговый остаток витрины
        в точности равен плану и гарантированно неотрицателен.
        """
        warehouse = StockLocation.objects.get(organization=organization, type=StockLocation.Type.WAREHOUSE)
        locations = {
            external_id: StockLocation.objects.get(organization=organization, fridge=fridge)
            for external_id, fridge in fridges.items()
        }

        # Сторонние движения (например, импорт CSV) тоже входят в итоговый остаток,
        # поэтому план пополнения учитывает их. Движения самого демо-набора
        # (продажи, списания) игнорируются: они компенсируются в sold/written_off.
        foreign_stock = {}
        for external_id, location in locations.items():
            for row in (
                InventoryMovement.objects.filter(stock_location=location)
                .exclude(external_id__startswith="SYNTH:")
                .values("product_id")
                .annotate(total=Sum("quantity"))
            ):
                foreign_stock[(external_id, row["product_id"])] = max(0, row["total"] or 0)

        fridge_movements = []
        for external_id in fridges:
            for sku, product in products.items():
                entries = batches[sku]["entries"]
                plan = stock_plan[external_id][sku]
                already_there = foreign_stock.get((external_id, product.pk), 0)
                plan_remaining = max(0, plan - already_there)
                exp_keep = min(plan_remaining, rng.randint(0, 3)) if batches[sku]["fresh"] else 0

                for batch_key, entry in entries.items():
                    sold = sold_units.get((external_id, sku, batch_key), 0)
                    written_off = write_off_units.get((external_id, sku, batch_key), 0)
                    if batch_key == "cur":
                        keep = max(0, plan_remaining - exp_keep)
                    elif batch_key == "exp":
                        keep = exp_keep
                    else:
                        keep = 0
                    quantity = sold + written_off + keep
                    if quantity <= 0:
                        continue
                    fridge_movements.append(
                        InventoryMovement(
                            organization=organization,
                            stock_location=locations[external_id],
                            product=product,
                            batch=entry["batch"],
                            movement_type=InventoryMovement.Type.RECEIPT,
                            quantity=quantity,
                            unit_cost=product.cost_price,
                            occurred_at=min(now - timedelta(minutes=5), entry["receipt_at"]),
                            source_type=InventoryMovement.Source.SYSTEM,
                            external_id=f"SYNTH:RESTOCK:{external_id}:{entry['batch'].batch_number}",
                            reason="Демонстрационная поставка на витрину",
                            metadata={"demo": True},
                        )
                    )

        # Складской клад покрывает все поставки на витрины плюс страховой запас.
        delivered = {}
        for movement in fridge_movements:
            delivered[movement.batch_id] = delivered.get(movement.batch_id, 0) + movement.quantity

        warehouse_movements = []
        for sku, info in batches.items():
            product = products[sku]
            for entry in info["entries"].values():
                batch = entry["batch"]
                warehouse_movements.append(
                    InventoryMovement(
                        organization=organization,
                        stock_location=warehouse,
                        product=product,
                        batch=batch,
                        movement_type=InventoryMovement.Type.RECEIPT,
                        quantity=delivered.get(batch.pk, 0) + 400,
                        unit_cost=product.cost_price,
                        occurred_at=min(now, batch.produced_at),
                        source_type=InventoryMovement.Source.SYSTEM,
                        external_id=f"SYNTH:RECEIPT:{batch.batch_number}",
                        reason="Демонстрационный клад склада",
                        metadata={"demo": True},
                    )
                )

        InventoryMovement.objects.bulk_create(warehouse_movements)
        InventoryMovement.objects.bulk_create(fridge_movements)

    # ------------------------------------------------------------------
    # Предупреждения
    # ------------------------------------------------------------------
    def _create_demo_alerts(self, organization, fridges, products, now):
        alerts = []
        for batch in Batch.objects.filter(
            organization=organization,
            status=Batch.Status.ACTIVE,
            expires_at__gt=now,
            expires_at__lte=now + timedelta(days=2),
        ).select_related("product"):
            alerts.append(
                Alert(
                    organization=organization,
                    fridge=None,
                    batch=batch,
                    alert_type=(
                        Alert.Type.EXPIRY_24H if batch.expires_at <= now + timedelta(hours=24) else Alert.Type.EXPIRY_48H
                    ),
                    severity="WARNING",
                    status="OPEN",
                    message=(
                        f"Демо: партия {batch.batch_number} по товару {batch.product.name} "
                        f"истекает {batch.expires_at:%d.%m.%Y %H:%M}"
                    ),
                )
            )

        for fridge in fridges.values():
            location = StockLocation.objects.get(organization=organization, fridge=fridge)
            totals = {
                row["product_id"]: row["total"] or 0
                for row in InventoryMovement.objects.filter(stock_location=location)
                .values("product_id")
                .annotate(total=Sum("quantity"))
            }
            for product in products.values():
                if totals.get(product.pk, 0) <= LOW_STOCK_THRESHOLD:
                    alerts.append(
                        Alert(
                            organization=organization,
                            fridge=fridge,
                            batch=None,
                            alert_type=Alert.Type.POTENTIAL_STOCKOUT,
                            severity="WARNING",
                            status="OPEN",
                            message=f"Демо: возможен дефицит {product.name} в {fridge.name}.",
                        )
                    )
        Alert.objects.bulk_create(alerts)

    # ------------------------------------------------------------------
    # Рекомендации
    # ------------------------------------------------------------------
    def _create_demo_forecasts(self, organization):
        """Строит рекомендации исключительно расчётом модели.

        Прежний запасной вариант проставлял всем позициям одинаковые 12/9 единиц —
        отсюда «у всех пополнение 9». Теперь остаток витрины правдоподобный, и
        ``generate_forecasts`` сама даёт разные количества, а части товаров
        пополнение не требуется вовсе.

        Используется единственная версия модели ``weighted-v1``: переименование
        версии в ``weighted-v1-demo-business`` приводило к дублям — повторный
        расчёт создавал вторую запись на ту же пару «холодильник + товар».
        Уникальность пары на дату гарантирует constraint модели Forecast, а
        демо-происхождение помечается в ``explanation``.
        """
        tomorrow = timezone.localdate() + timedelta(days=1)
        generate_forecasts(organization, target_date=tomorrow)
        Forecast.objects.filter(
            organization=organization,
            forecast_date=tomorrow,
            model_version="weighted-v1",
        ).update(explanation={"demo_source": "business_demo"})
        return Forecast.objects.filter(
            organization=organization,
            forecast_date=tomorrow,
            model_version="weighted-v1",
        )

    # ------------------------------------------------------------------
    # Отчёт
    # ------------------------------------------------------------------
    @staticmethod
    def _fridge_stock(fridge):
        location = StockLocation.objects.get(fridge=fridge)
        return InventoryMovement.objects.filter(stock_location=location).aggregate(total=Sum("quantity"))["total"] or 0

    def _final_report(self, organization):
        now = timezone.now()
        last_30 = now - timedelta(days=30)
        paid_sales = Sale.objects.filter(
            organization=organization,
            payment_status=Sale.PaymentStatus.PAID,
            sold_at__gte=now - timedelta(days=HISTORY_DAYS),
            external_id__startswith="SYNTH-",
        )
        revenue_60 = paid_sales.aggregate(total=Sum("total_amount"))["total"] or Decimal("0")
        paid_30 = paid_sales.filter(sold_at__gte=last_30)
        revenue_30 = paid_30.aggregate(total=Sum("total_amount"))["total"] or Decimal("0")
        cogs_30 = (
            SaleItem.objects.filter(sale__in=paid_30)
            .annotate(cost=F("unit_cost") * F("quantity"))
            .aggregate(total=Sum("cost"))["total"]
            or Decimal("0")
        )
        gross_profit = revenue_30 - cogs_30
        gross_margin = (gross_profit / revenue_30 * Decimal("100")) if revenue_30 else Decimal("0")

        write_off_total = abs(
            InventoryMovement.objects.filter(
                organization=organization,
                movement_type=InventoryMovement.Type.WRITE_OFF,
                occurred_at__gte=last_30,
                external_id__startswith="SYNTH:",
            ).annotate(loss=F("unit_cost") * F("quantity")).aggregate(total=Sum("loss"))["total"]
            or Decimal("0")
        )
        write_off_ratio = (write_off_total / revenue_30 * Decimal("100")) if revenue_30 else Decimal("0")

        fridges = list(Fridge.objects.filter(organization=organization))
        stocks = {fridge.name: self._fridge_stock(fridge) for fridge in fridges}
        stock_values = list(stocks.values())
        recommendations = Forecast.objects.filter(
            organization=organization,
            forecast_date__gte=timezone.localdate(),
            model_version="weighted-v1",
            replenish_quantity__gt=0,
        )
        quantities = sorted(set(recommendations.values_list("replenish_quantity", flat=True)))
        status_counts = dict(
            Sale.objects.filter(
                organization=organization, external_id__startswith="SYNTH-"
            ).values_list("payment_status").annotate(count=Count("payment_status"))
        )

        return {
            "fridges": len(fridges),
            "products": Product.objects.filter(organization=organization).count(),
            "sales_total": Sale.objects.filter(organization=organization, external_id__startswith="SYNTH-").count(),
            "sales_paid": paid_sales.count(),
            "status_counts": status_counts,
            "revenue_60": revenue_60,
            "revenue_30": revenue_30,
            "cogs_30": cogs_30,
            "gross_profit": gross_profit,
            "gross_margin": gross_margin,
            "avg_check": (revenue_60 / Decimal(paid_sales.count())) if paid_sales.exists() else Decimal("0"),
            "write_off_total": write_off_total,
            "write_off_ratio": write_off_ratio,
            "warnings": Alert.objects.filter(organization=organization, status="OPEN").count(),
            "recommendations": recommendations.count(),
            "replenish_quantities": quantities,
            "stocks": stocks,
            "stock_min": min(stock_values) if stock_values else 0,
            "stock_max": max(stock_values) if stock_values else 0,
        }

    # ------------------------------------------------------------------
    # Точка входа
    # ------------------------------------------------------------------
    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.ALLOW_DEMO_SEED:
            from django.core.management.base import CommandError
            raise CommandError("На сервере используйте bootstrap_pilot, а не seed_business_demo.")
        organization = self._ensure_default_demo_data()
        if not options.get("replace") and self._has_synthetic_demo_data(organization):
            self.stdout.write("Расширенные демонстрационные данные уже созданы. Используйте --replace для пересоздания.")
            return
        if options.get("replace"):
            self._delete_synthetic_demo_data(organization)

        # Стартовое наполнение seed_demo расширенному набору не нужно: оно
        # искажало остатки, сроки годности и рекомендации внутри демо-организации.
        purged, neutralized = self._purge_standard_demo_batches(organization)
        demo_import_sales = self._purge_standard_demo_sales(organization)

        provider = self._ensure_provider(organization)
        fridges = self._ensure_fridges(organization, provider)
        products = self._ensure_products(organization)
        StockLocation.objects.get_or_create(
            organization=organization,
            type=StockLocation.Type.WAREHOUSE,
            name="Центральный склад",
        )
        StockLocation.objects.get_or_create(
            organization=organization,
            type=StockLocation.Type.WRITE_OFF_ZONE,
            name="Зона списания",
        )

        now = timezone.now()
        today = timezone.localdate()
        rng = random.Random(20260916)

        batches = self._create_batches(organization, products, now, today, rng)
        stock_plan = {external_id: self._plan_fridge_stock(rng, list(products)) for external_id in fridges}
        sold_units = self._create_sales_history(organization, provider, fridges, products, batches, now, today, rng)
        write_off_units, _ = self._create_write_offs(organization, fridges, products, batches, sold_units, today, rng)
        self._create_receipts(organization, fridges, products, batches, sold_units, write_off_units, stock_plan, now, rng)
        self._create_demo_alerts(organization, fridges, products, now)
        self._create_demo_forecasts(organization)

        metrics = self._final_report(organization)
        stock_lines = "\n".join(f"  {name}: {value} шт." for name, value in sorted(metrics["stocks"].items()))
        self.stdout.write(
            self.style.SUCCESS(
                "\nРасширенная демонстрационная база создана.\n\n"
                f"Организация: {organization.name}\n"
                f"Убрано стандартных партий seed_demo: {purged}, нейтрализовано: {neutralized}\n"
                f"Удалено продаж демо-импорта demo_sales.csv: {demo_import_sales}\n"
                f"Холодильников: {metrics['fridges']}\n"
                f"Товаров: {metrics['products']}\n"
                f"Продаж всего / оплаченных: {metrics['sales_total']} / {metrics['sales_paid']}\n"
                f"Статусы продаж: {metrics['status_counts']}\n"
                f"Выручка за 60 дней: {metrics['revenue_60'].quantize(Decimal('1.00'))} ₽\n"
                f"Выручка за 30 дней: {metrics['revenue_30'].quantize(Decimal('1.00'))} ₽\n"
                f"Себестоимость проданных за 30 дней: {metrics['cogs_30'].quantize(Decimal('1.00'))} ₽\n"
                f"Валовая прибыль за 30 дней: {metrics['gross_profit'].quantize(Decimal('1.00'))} ₽\n"
                f"Валовая маржа: {metrics['gross_margin'].quantize(Decimal('0.1'))} %\n"
                f"Средний чек: {metrics['avg_check'].quantize(Decimal('1.00'))} ₽\n"
                f"Стоимость списаний за 30 дней: {metrics['write_off_total'].quantize(Decimal('1.00'))} ₽\n"
                f"Доля списаний: {metrics['write_off_ratio'].quantize(Decimal('0.1'))} %\n"
                f"Остаток по холодильникам (мин/макс): {metrics['stock_min']} / {metrics['stock_max']} шт.\n"
                f"{stock_lines}\n"
                f"Активных предупреждений: {metrics['warnings']}\n"
                f"Рекомендаций к пополнению: {metrics['recommendations']}\n"
                f"Разные количества пополнения: {metrics['replenish_quantities']}\n\n"
                f"Логин: {DEMO_USER}\n"
                f"Пароль: {DEMO_PASSWORD}\n"
            )
        )
