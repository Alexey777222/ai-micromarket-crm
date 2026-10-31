import uuid

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name="ID")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="обновлено")

    class Meta:
        abstract = True


class Organization(UUIDModel):
    name = models.CharField(max_length=200, verbose_name="наименование")
    timezone = models.CharField(max_length=64, default="Europe/Moscow", verbose_name="часовой пояс")
    is_active = models.BooleanField(default=True, verbose_name="активна")

    class Meta:
        verbose_name = "Организация"
        verbose_name_plural = "Организации"

    def __str__(self):
        return self.name


class Membership(UUIDModel):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Владелец"
        OPERATOR = "OPERATOR", "Оператор"
        MERCHANDISER = "MERCHANDISER", "Мерчендайзер"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="пользователь")
    role = models.CharField(max_length=20, choices=Role.choices, verbose_name="роль")
    telegram_user_id = models.BigIntegerField(null=True, blank=True, verbose_name="Telegram ID")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="unique_org_membership")
        ]
        verbose_name = "Участник организации"
        verbose_name_plural = "Участники организации"


class Location(UUIDModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    name = models.CharField(max_length=200, verbose_name="наименование")
    address = models.CharField(max_length=500, verbose_name="адрес")
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True, verbose_name="широта"
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True, verbose_name="долгота"
    )
    working_hours = models.CharField(max_length=200, blank=True, verbose_name="рабочие часы")
    visit_days = models.CharField(max_length=100, blank=True, verbose_name="дни визита")
    is_active = models.BooleanField(default=True, verbose_name="активна")

    class Meta:
        verbose_name = "Точка установки"
        verbose_name_plural = "Точки установки"

    def __str__(self):
        return self.name


class DeviceProvider(UUIDModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    code = models.CharField(max_length=40, verbose_name="код")
    name = models.CharField(max_length=200, verbose_name="наименование")
    adapter_type = models.CharField(max_length=100, default="canonical_csv", verbose_name="тип адаптера")
    is_active = models.BooleanField(default=True, verbose_name="активен")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="unique_provider_code")
        ]
        verbose_name = "Поставщик оборудования"
        verbose_name_plural = "Поставщики оборудования"

    def __str__(self):
        return f"{self.code}: {self.name}"


class Fridge(UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Активен"
        MAINTENANCE = "MAINTENANCE", "Обслуживание"
        DISABLED = "DISABLED", "Отключён"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, verbose_name="точка")
    provider = models.ForeignKey(DeviceProvider, on_delete=models.PROTECT, verbose_name="поставщик")
    name = models.CharField(max_length=200, verbose_name="наименование")
    serial_number = models.CharField(max_length=100, verbose_name="серийный номер")
    external_id = models.CharField(max_length=100, verbose_name="внешний ID")
    model = models.CharField(max_length=100, blank=True, verbose_name="модель")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="статус",
    )
    service_qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, verbose_name="QR токен")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider", "external_id"],
                name="unique_provider_fridge_external_id",
            )
        ]
        verbose_name = "Холодильник"
        verbose_name_plural = "Холодильники"

    def __str__(self):
        return self.name


class Product(UUIDModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    sku = models.CharField(max_length=80, verbose_name="SKU")
    barcode = models.CharField(max_length=80, blank=True, verbose_name="штрихкод")
    name = models.CharField(max_length=200, verbose_name="наименование")
    category = models.CharField(max_length=100, blank=True, verbose_name="категория")
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="себестоимость")
    sale_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="цена продажи")
    shelf_life_hours = models.PositiveIntegerField(null=True, blank=True, verbose_name="срок хранения")
    is_active = models.BooleanField(default=True, verbose_name="активен")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "sku"], name="unique_product_sku")
        ]
        verbose_name = "Товар"
        verbose_name_plural = "Товары"

    def __str__(self):
        return f"{self.sku} — {self.name}"


class Batch(UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Активна"
        BLOCKED = "BLOCKED", "Заблокирована"
        EXPIRED = "EXPIRED", "Просрочена"
        RECALLED = "RECALLED", "Отозвана"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="товар")
    batch_number = models.CharField(max_length=100, verbose_name="номер партии")
    produced_at = models.DateTimeField(null=True, blank=True, verbose_name="произведено")
    expires_at = models.DateTimeField(verbose_name="годен до")
    supplier = models.CharField(max_length=200, blank=True, verbose_name="поставщик")
    purchase_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="себестоимость партии",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, verbose_name="статус")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "product", "batch_number"],
                name="unique_product_batch",
            )
        ]
        ordering = ["expires_at"]
        verbose_name = "Партия"
        verbose_name_plural = "Партии"

    def __str__(self):
        return f"{self.product.sku}/{self.batch_number}"


class StockLocation(UUIDModel):
    class Type(models.TextChoices):
        WAREHOUSE = "WAREHOUSE", "Склад"
        VEHICLE = "VEHICLE", "Автомобиль"
        FRIDGE = "FRIDGE", "Холодильник"
        WRITE_OFF_ZONE = "WRITE_OFF_ZONE", "Зона списания"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    type = models.CharField(max_length=20, choices=Type.choices, verbose_name="тип")
    name = models.CharField(max_length=200, verbose_name="наименование")
    fridge = models.OneToOneField(Fridge, null=True, blank=True, on_delete=models.CASCADE, verbose_name="холодильник")
    assigned_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="назначенный пользователь")
    is_active = models.BooleanField(default=True, verbose_name="активно")

    class Meta:
        verbose_name = "Место хранения"
        verbose_name_plural = "Места хранения"

    def clean(self):
        if self.type == self.Type.FRIDGE and not self.fridge_id:
            raise ValidationError("Для места типа FRIDGE нужно выбрать холодильник.")
        if self.type != self.Type.FRIDGE and self.fridge_id:
            raise ValidationError("Холодильник допустим только для места типа FRIDGE.")

    def __str__(self):
        return self.name


class StockTransfer(UUIDModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Черновик"
        POSTED = "POSTED", "Проведено"
        CANCELLED = "CANCELLED", "Отменено"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    source_location = models.ForeignKey(
        StockLocation,
        on_delete=models.PROTECT,
        related_name="outgoing_transfers",
        verbose_name="источник",
    )
    destination_location = models.ForeignKey(
        StockLocation,
        on_delete=models.PROTECT,
        related_name="incoming_transfers",
        verbose_name="получатель",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, verbose_name="статус")
    occurred_at = models.DateTimeField(verbose_name="дата операции")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="создано пользователем")
    reason = models.CharField(max_length=300, blank=True, verbose_name="причина")
    external_id = models.CharField(max_length=100, blank=True, verbose_name="внешний ID")

    class Meta:
        verbose_name = "Перемещение"
        verbose_name_plural = "Перемещения"

    def clean(self):
        if self.source_location_id == self.destination_location_id:
            raise ValidationError("Источник и получатель должны различаться.")


class StockTransferItem(UUIDModel):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="items", verbose_name="перемещение")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="товар")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, verbose_name="партия")
    quantity = models.PositiveIntegerField(verbose_name="количество")
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="себестоимость")

    class Meta:
        verbose_name = "Позиция перемещения"
        verbose_name_plural = "Позиции перемещения"


class InventoryMovement(UUIDModel):
    class Type(models.TextChoices):
        INITIAL = "INITIAL", "Начальный остаток"
        RECEIPT = "RECEIPT", "Приёмка"
        TRANSFER_IN = "TRANSFER_IN", "Перемещение: приход"
        TRANSFER_OUT = "TRANSFER_OUT", "Перемещение: расход"
        SALE = "SALE", "Продажа"
        RETURN = "RETURN", "Возврат"
        WRITE_OFF = "WRITE_OFF", "Списание"
        INVENTORY_ADJUSTMENT = "INVENTORY_ADJUSTMENT", "Корректировка"

    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Вручную"
        CSV = "CSV", "CSV"
        DEVICE_API = "DEVICE_API", "API аппарата"
        SYSTEM = "SYSTEM", "Система"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    stock_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, verbose_name="место хранения")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="товар")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, verbose_name="партия")
    transfer = models.ForeignKey(
        StockTransfer,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="перемещение",
    )
    movement_type = models.CharField(max_length=30, choices=Type.choices, verbose_name="тип движения")
    quantity = models.IntegerField(verbose_name="количество")
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="себестоимость")
    occurred_at = models.DateTimeField(verbose_name="дата операции")
    source_type = models.CharField(max_length=20, choices=Source.choices, verbose_name="источник")
    external_id = models.CharField(max_length=200, blank=True, verbose_name="внешний ID")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="создано пользователем")
    reason = models.CharField(max_length=300, blank=True, verbose_name="причина")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="метаданные")

    class Meta:
        indexes = [
            models.Index(fields=["organization", "stock_location", "product", "occurred_at"])
        ]
        verbose_name = "Движение товара"
        verbose_name_plural = "Движения товаров"


class Sale(UUIDModel):
    class PaymentStatus(models.TextChoices):
        PAID = "PAID", "Оплачена"
        REFUNDED = "REFUNDED", "Возврат"
        CANCELLED = "CANCELLED", "Отменена"
        UNKNOWN = "UNKNOWN", "Неизвестно"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    provider = models.ForeignKey(DeviceProvider, on_delete=models.PROTECT, verbose_name="поставщик")
    fridge = models.ForeignKey(Fridge, on_delete=models.PROTECT, verbose_name="холодильник")
    external_id = models.CharField(max_length=120, verbose_name="внешний ID")
    sold_at = models.DateTimeField(verbose_name="дата продажи")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="сумма продажи")
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, verbose_name="статус оплаты")
    receipt_number = models.CharField(max_length=100, blank=True, verbose_name="номер чека")
    raw_payload = models.JSONField(default=dict, verbose_name="сырой JSON")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider", "fridge", "external_id"],
                name="unique_external_sale",
            )
        ]
        verbose_name = "Продажа"
        verbose_name_plural = "Продажи"


class SaleItem(UUIDModel):
    class Allocation(models.TextChoices):
        ACTUAL = "ACTUAL", "Фактическая"
        ESTIMATED_FEFO = "ESTIMATED_FEFO", "Расчётная FEFO"
        UNKNOWN = "UNKNOWN", "Неизвестна"

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items", verbose_name="продажа")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="товар")
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.PROTECT, verbose_name="партия")
    batch_allocation_source = models.CharField(
        max_length=20,
        choices=Allocation.choices,
        default=Allocation.UNKNOWN,
        verbose_name="источник распределения",
    )
    quantity = models.PositiveIntegerField(verbose_name="количество")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="цена продажи")
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="себестоимость")
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="скидка")

    class Meta:
        verbose_name = "Позиция продажи"
        verbose_name_plural = "Позиции продаж"


class ImportJob(UUIDModel):
    class Status(models.TextChoices):
        UPLOADED = "UPLOADED", "Загружен"
        VALIDATED = "VALIDATED", "Проверен"
        FAILED = "FAILED", "Ошибка"
        COMMITTED = "COMMITTED", "Импортирован"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    provider = models.ForeignKey(DeviceProvider, on_delete=models.PROTECT, verbose_name="поставщик")
    file_hash = models.CharField(max_length=64, verbose_name="хеш файла")
    filename = models.CharField(max_length=255, verbose_name="имя файла")
    status = models.CharField(max_length=20, choices=Status.choices, verbose_name="статус")
    total_rows = models.PositiveIntegerField(default=0, verbose_name="всего строк")
    valid_rows = models.PositiveIntegerField(default=0, verbose_name="валидных строк")
    error_rows = models.PositiveIntegerField(default=0, verbose_name="ошибок")
    duplicate_rows = models.PositiveIntegerField(default=0, verbose_name="дублей")
    error_report = models.JSONField(default=list, blank=True, verbose_name="отчёт об ошибках")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="создано пользователем")
    committed_at = models.DateTimeField(null=True, blank=True, verbose_name="дата импорта")

    class Meta:
        verbose_name = "Импорт"
        verbose_name_plural = "История импортов"


class Alert(UUIDModel):
    class Type(models.TextChoices):
        EXPIRY_48H = "EXPIRY_48H", "Истекает за 48 часов"
        EXPIRY_24H = "EXPIRY_24H", "Истекает за 24 часа"
        EXPIRED = "EXPIRED", "Просрочено"
        POTENTIAL_STOCKOUT = "POTENTIAL_STOCKOUT", "Предполагаемый дефицит"
        IMPORT_ERROR = "IMPORT_ERROR", "Ошибка импорта"
        STOCK_MISMATCH = "STOCK_MISMATCH", "Расхождение остатка"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    fridge = models.ForeignKey(Fridge, null=True, blank=True, on_delete=models.CASCADE, verbose_name="холодильник")
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.CASCADE, verbose_name="партия")
    alert_type = models.CharField(max_length=30, choices=Type.choices, verbose_name="тип предупреждения")
    severity = models.CharField(max_length=10, default="WARNING", verbose_name="важность")
    status = models.CharField(max_length=20, default="OPEN", verbose_name="статус")
    message = models.CharField(max_length=500, verbose_name="сообщение")

    class Meta:
        verbose_name = "Предупреждение"
        verbose_name_plural = "Предупреждения"


class Forecast(UUIDModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="организация")
    fridge = models.ForeignKey(Fridge, on_delete=models.CASCADE, verbose_name="холодильник")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name="товар")
    forecast_date = models.DateField(verbose_name="дата прогноза")
    predicted_quantity = models.PositiveIntegerField(verbose_name="прогнозируемое количество")
    replenish_quantity = models.PositiveIntegerField(verbose_name="количество к пополнению")
    model_version = models.CharField(max_length=30, default="weighted-v1", verbose_name="версия модели")
    explanation = models.JSONField(default=dict, verbose_name="объяснение")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "fridge", "product", "forecast_date", "model_version"],
                name="unique_forecast",
            )
        ]
        verbose_name = "Рекомендация"
        verbose_name_plural = "Рекомендации"
