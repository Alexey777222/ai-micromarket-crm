from django.contrib import admin

from . import models


@admin.register(models.Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "timezone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(models.Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("organization", "user", "role", "telegram_user_id")
    list_filter = ("organization", "role")
    search_fields = ("user__username", "organization__name", "telegram_user_id")


@admin.register(models.Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "address", "is_active")
    list_filter = ("organization", "is_active")
    search_fields = ("name", "address")


@admin.register(models.DeviceProvider)
class DeviceProviderAdmin(admin.ModelAdmin):
    list_display = ("organization", "code", "name", "adapter_type", "is_active")
    list_filter = ("organization", "adapter_type", "is_active")
    search_fields = ("code", "name")


@admin.register(models.Fridge)
class FridgeAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "location", "provider", "status")
    list_filter = ("organization", "provider", "status")
    search_fields = ("name", "serial_number", "external_id")


@admin.register(models.Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "category", "cost_price", "sale_price", "is_active")
    search_fields = ("sku", "name", "barcode")
    list_filter = ("organization", "category", "is_active")


@admin.register(models.Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("batch_number", "product", "supplier", "expires_at", "status")
    list_filter = ("organization", "status", "expires_at")
    search_fields = ("batch_number", "product__sku", "supplier")


@admin.register(models.StockLocation)
class StockLocationAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "type", "fridge", "is_active")
    list_filter = ("organization", "type", "is_active")
    search_fields = ("name", "fridge__name")


@admin.register(models.StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = (
        "external_id",
        "organization",
        "source_location",
        "destination_location",
        "status",
        "occurred_at",
    )
    list_filter = ("organization", "status", "occurred_at")
    search_fields = ("external_id", "reason")
    ordering = ("-occurred_at",)


@admin.register(models.StockTransferItem)
class StockTransferItemAdmin(admin.ModelAdmin):
    list_display = ("transfer", "product", "batch", "quantity", "unit_cost")
    search_fields = ("product__sku", "batch__batch_number")
    list_filter = ("transfer__organization",)


@admin.register(models.InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = (
        "occurred_at",
        "organization",
        "stock_location",
        "product",
        "batch",
        "movement_type",
        "quantity",
    )
    list_filter = ("organization", "movement_type", "source_type", "stock_location")
    search_fields = ("product__sku", "product__name", "external_id")
    readonly_fields = ("created_at", "updated_at")
    exclude = ("metadata",)
    ordering = ("-occurred_at",)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(models.Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("sold_at", "organization", "fridge", "provider", "total_amount", "payment_status")
    search_fields = ("external_id", "receipt_number", "fridge__name")
    list_filter = ("organization", "provider", "fridge", "payment_status")
    ordering = ("-sold_at",)
    exclude = ("raw_payload",)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(models.SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = ("sale", "product", "batch", "quantity", "unit_price", "unit_cost")
    search_fields = ("product__sku", "product__name", "sale__external_id")
    list_filter = ("sale__organization", "batch_allocation_source")


@admin.register(models.ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    list_display = (
        "filename",
        "organization",
        "provider",
        "status",
        "total_rows",
        "valid_rows",
        "error_rows",
        "created_at",
    )
    list_filter = ("organization", "provider", "status")
    search_fields = ("filename", "provider__code", "file_hash")
    readonly_fields = ("file_hash", "error_report", "created_at", "updated_at")
    exclude = ("error_report",)


@admin.register(models.Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("alert_type", "organization", "fridge", "batch", "severity", "status")
    list_filter = ("organization", "alert_type", "severity", "status")
    search_fields = ("message", "fridge__name", "batch__batch_number")


@admin.register(models.Forecast)
class ForecastAdmin(admin.ModelAdmin):
    list_display = (
        "forecast_date",
        "organization",
        "fridge",
        "product",
        "predicted_quantity",
        "replenish_quantity",
    )
    list_filter = ("organization", "forecast_date", "fridge")
    search_fields = ("product__name", "product__sku", "fridge__name")
    readonly_fields = ("created_at", "updated_at")
    exclude = ("explanation",)


admin.site.site_header = "MicroMarket Control"
admin.site.site_title = "MicroMarket Control"
admin.site.index_title = "Управление"
