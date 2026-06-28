"""Seed demo login credentials so the app is usable without manual signup.

Idempotent: re-running updates the password/name rather than erroring. The
post_save signal on User auto-creates the reward + subscription profiles, so
seeded users behave exactly like real ones.

    python manage.py seed_demo
    python manage.py seed_demo --email me@example.com --password "Secret123!" --name "Me"
"""

from django.core.management.base import BaseCommand

from apps.accounts.models import User

# Default demo accounts (email, password, name). Passwords meet the API's
# strength rules so these also work when created through auth/email/.
DEMO_USERS = [
    ("demo@playstudy.app", "Playstudy123!", "Demo Learner"),
    ("student@playstudy.app", "Playstudy123!", "Sam Student"),
    ("parent@playstudy.app", "Playstudy123!", "Pat Parent"),
]


class Command(BaseCommand):
    help = "Create or update demo login credentials."

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Create/update a single user with this email")
        parser.add_argument("--password", default="Playstudy123!")
        parser.add_argument("--name", default="Demo User")

    def handle(self, *args, **opts):
        if opts.get("email"):
            users = [(opts["email"], opts["password"], opts["name"])]
        else:
            users = DEMO_USERS

        for email, password, name in users:
            email = email.strip().lower()
            user, created = User.objects.get_or_create(
                email=email,
                defaults={"name": name, "provider": User.Provider.EMAIL},
            )
            user.name = name
            user.set_password(password)
            user.is_active = True
            user.save()
            verb = "Created" if created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(f"{verb} {email}  (password: {password})")
            )

        self.stdout.write(self.style.SUCCESS("Done."))
