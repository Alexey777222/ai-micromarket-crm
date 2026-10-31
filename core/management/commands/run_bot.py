import asyncio

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import Forecast, Membership

try:
    from aiogram import Bot, Dispatcher, Router
    from aiogram.filters import Command
    from aiogram.types import Message
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    Bot = None
    Dispatcher = None
    Router = None
    Command = None
    Message = None

if Router is not None:
    router = Router()

    @router.message(Command("start"))
    async def start(message: Message):
        membership = await sync_to_async(
            lambda: Membership.objects.filter(telegram_user_id=message.from_user.id).first()
        )()
        if membership:
            await message.answer("MicroMarket Control подключён. Команда: /replenishment")
        else:
            await message.answer(
                "Ваш Telegram ещё не привязан. Укажите telegram_user_id "
                "в Membership через админ-панель."
            )

    @router.message(Command("replenishment"))
    async def replenishment(message: Message):
        membership = await sync_to_async(
            lambda: Membership.objects.select_related("organization")
            .filter(telegram_user_id=message.from_user.id)
            .first()
        )()
        if not membership:
            await message.answer("Пользователь не привязан.")
            return

        def rows():
            return list(
                Forecast.objects.filter(organization=membership.organization, replenish_quantity__gt=0)
                .select_related("fridge", "product")
                .order_by("fridge__name", "product__name")[:30]
            )

        forecasts = await sync_to_async(rows)()
        if not forecasts:
            await message.answer(
                "Нет рассчитанных рекомендаций. Сначала запустите расчёт в веб-панели."
            )
            return
        text = "Пополнение:\n" + "\n".join(
            f"• {x.fridge.name}: {x.product.name} — {x.replenish_quantity} шт." for x in forecasts
        )
        await message.answer(text)
else:
    router = None


class Command(BaseCommand):
    help = "Запускает тестовый Telegram-бот."

    def handle(self, *args, **options):
        if Router is None or Bot is None or Dispatcher is None:
            raise CommandError(
                "Telegram-зависимости не установлены. Установите их командой:\n"
                "python -m pip install -r requirements-bot.txt"
            )

        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not token:
            import os

            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise CommandError("Укажите TELEGRAM_BOT_TOKEN в .env или окружении.")

        async def main():
            bot = Bot(token=token)
            dispatcher = Dispatcher()
            dispatcher.include_router(router)
            await dispatcher.start_polling(bot)

        asyncio.run(main())
