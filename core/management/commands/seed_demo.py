import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import (
    Batch,
    DeviceProvider,
    Fridge,
    InventoryMovement,
    Location,
    Membership,
    Organization,
    Product,
    StockLocation,
)


class Command(BaseCommand):
    help = "Создаёт демонстрационную организацию, 7 холодильников и остатки."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.ALLOW_DEMO_SEED:
            raise CommandError("На сервере используйте bootstrap_pilot, а не seed_demo.")
        organization, _ = Organization.objects.get_or_create(
            name="Демо-сеть микромаркетов", defaults={"timezone": "Europe/Moscow"}
        )
        user, created = User.objects.get_or_create(
            username="demo", defaults={"email": "demo@example.com"}
        )
        if created:
            if settings.IS_PRODUCTION:
                user.set_unusable_password()
                user.is_active = False
            else:
                user.set_password("demo12345")
                user.is_staff = True
                user.is_superuser = True
            user.save()
        Membership.objects.get_or_create(
            organization=organization,
            user=user,
            defaults={"role": Membership.Role.OWNER},
        )
        provider, _ = DeviceProvider.objects.get_or_create(
            organization=organization,
            code="DEMO",
            defaults={"name": "Демонстрационный CSV"},
        )
        warehouse, _ = StockLocation.objects.get_or_create(
            organization=organization,
            type=StockLocation.Type.WAREHOUSE,
            name="Центральный склад",
        )
        StockLocation.objects.get_or_create(
            organization=organization,
            type=StockLocation.Type.WRITE_OFF_ZONE,
            name="Зона списания",
        )
        fridges = []
        for index in range(1, 8):
            location, _ = Location.objects.get_or_create(
                organization=organization,
                name=f"Точка {index}",
                defaults={"address": f"Москва, демонстрационный адрес, {index}"},
            )
            fridge, _ = Fridge.objects.get_or_create(
                organization=organization,
                provider=provider,
                external_id=f"F-{index:03d}",
                defaults={
                    "location": location,
                    "name": f"Холодильник {index}",
                    "serial_number": f"DEMO-{index:04d}",
                    "model": "Demo Smart Fridge",
                },
            )
            StockLocation.objects.get_or_create(
                organization=organization,
                type=StockLocation.Type.FRIDGE,
                fridge=fridge,
                defaults={"name": fridge.name},
            )
            fridges.append(fridge)

        product_specs = [
            ("SAND-CHICKEN", "Сэндвич с курицей", "Сэндвичи", "115", "249", 72),
            ("SAND-HAM", "Сэндвич с ветчиной", "Сэндвичи", "120", "259", 72),
            ("SALAD-CAESAR", "Салат Цезарь", "Салаты", "165", "349", 48),
            ("SALAD-GREEK", "Салат Греческий", "Салаты", "150", "329", 48),
            ("PASTA-BOLOGNESE", "Паста Болоньезе", "Горячее", "190", "399", 72),
            ("RICE-CHICKEN", "Рис с курицей", "Горячее", "175", "379", 72),
            ("DESSERT-CHEESE", "Чизкейк", "Десерты", "105", "229", 96),
            ("WATER-05", "Вода 0,5 л", "Напитки", "25", "79", 4320),
            ("COLA-05", "Кола 0,5 л", "Напитки", "55", "129", 4320),
            ("BAR-NUT", "Ореховый батончик", "Снеки", "45", "119", 2160),
        ]
        now = timezone.now()
        for idx, (sku, name, category, cost, price, shelf_life) in enumerate(product_specs):
            product, _ = Product.objects.get_or_create(
                organization=organization,
                sku=sku,
                defaults={
                    "name": name,
                    "category": category,
                    "cost_price": Decimal(cost),
                    "sale_price": Decimal(price),
                    "shelf_life_hours": shelf_life,
                },
            )
            expires = now + timedelta(hours=36 if idx < 2 else shelf_life)
            batch, _ = Batch.objects.get_or_create(
                organization=organization,
                product=product,
                batch_number=f"DEMO-{now:%Y%m%d}-{idx:02d}",
                defaults={
                    "produced_at": now - timedelta(hours=12),
                    "expires_at": expires,
                    "supplier": "Демо-производство",
                    "purchase_cost": product.cost_price,
                },
            )
            if not InventoryMovement.objects.filter(
                stock_location=warehouse, product=product, batch=batch
            ).exists():
                InventoryMovement.objects.create(
                    organization=organization,
                    stock_location=warehouse,
                    product=product,
                    batch=batch,
                    movement_type=InventoryMovement.Type.INITIAL,
                    quantity=200,
                    unit_cost=product.cost_price,
                    occurred_at=now - timedelta(days=30),
                    source_type=InventoryMovement.Source.SYSTEM,
                    reason="Демонстрационный остаток",
                )
                for fridge in fridges:
                    fridge_location = StockLocation.objects.get(fridge=fridge)
                    # Небольшие остатки нужны, чтобы после импорта тестового CSV
                    # на дашборде появились рекомендации к пополнению.
                    quantity = random.Random(f"{sku}-{fridge.external_id}").randint(0, 2)
                    InventoryMovement.objects.create(
                        organization=organization,
                        stock_location=fridge_location,
                        product=product,
                        batch=batch,
                        movement_type=InventoryMovement.Type.INITIAL,
                        quantity=quantity,
                        unit_cost=product.cost_price,
                        occurred_at=now - timedelta(days=30),
                        source_type=InventoryMovement.Source.SYSTEM,
                        reason="Демонстрационный остаток",
                    )
        self.stdout.write(self.style.SUCCESS("Демо готово: логин demo, пароль demo12345"))
