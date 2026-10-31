import getpass
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test.utils import override_settings

from core.models import Membership, Organization


class Command(BaseCommand):
    help = "Однократное наполнение ПУСТОЙ серверной базы и создание владельца без прав администратора."

    def add_arguments(self, parser):
        parser.add_argument("--confirm-demo", action="store_true")
        parser.add_argument("--username", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.IS_PRODUCTION or not options["confirm_demo"]:
            raise CommandError("Нужны MMC_ENV=production и --confirm-demo.")
        User = get_user_model()
        if Organization.objects.exists() or User.objects.exists():
            raise CommandError("База не пустая. Повторное наполнение запрещено; данные не изменены.")
        user = User(username=options["username"], is_staff=False, is_superuser=False)
        if user.username.lower() == "demo":
            raise CommandError("Выберите индивидуальный логин, не demo.")
        try:
            user.full_clean(exclude=["password"])
            password = getpass.getpass("Пароль владельца (не менее 12 символов): ")
            if password != getpass.getpass("Повторите пароль: "):
                raise CommandError("Пароли не совпадают.")
            validate_password(password, user=user)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        # Legacy seed output contains a local demo password; never expose it here.
        with override_settings(ALLOW_DEMO_SEED=True):
            call_command("seed_business_demo", stdout=StringIO())
        demo = User.objects.get(username="demo")
        if demo.is_active or demo.has_usable_password() or demo.is_superuser:
            raise CommandError("Небезопасная демо-учётная запись; транзакция отменена.")
        user.set_password(password)
        user.save()
        Membership.objects.create(
            user=user, organization=Organization.objects.get(name="Демо-сеть микромаркетов"),
            role=Membership.Role.OWNER,
        )
        self.stdout.write(self.style.SUCCESS(
            "Пилот создан. Владелец входит через /accounts/login/. "
            "Учётная запись demo отключена. Пароль не записан в журналы."
        ))
