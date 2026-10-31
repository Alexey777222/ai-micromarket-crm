from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.models import Membership


class Command(BaseCommand):
    help = "Reject unsafe demo accounts before starting the server."

    def handle(self, *args, **options):
        if not settings.IS_PRODUCTION:
            raise CommandError("This check is for MMC_ENV=production.")
        User = get_user_model()
        if User.objects.filter(username__iexact="demo", is_active=True).exists():
            raise CommandError("Active demo account detected; do not expose this database.")
        if not Membership.objects.filter(
            role=Membership.Role.OWNER, organization__is_active=True,
            user__is_active=True, user__is_staff=False, user__is_superuser=False,
        ).exists():
            raise CommandError("No active non-admin owner. Run bootstrap_pilot on an EMPTY database.")
        self.stdout.write(self.style.SUCCESS("Pilot account checks passed."))
