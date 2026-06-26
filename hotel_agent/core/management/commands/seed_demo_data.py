"""
Management command to seed the database with demo data.
Usage: python manage.py seed_demo_data
"""
import random
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Seed the database with demo hotel data"

    ROOM_DATA = [
        {"number": "101", "floor": 1, "room_type": "standard", "price": "120.00", "capacity": 2},
        {"number": "102", "floor": 1, "room_type": "standard", "price": "120.00", "capacity": 2},
        {"number": "201", "floor": 2, "room_type": "deluxe", "price": "200.00", "capacity": 2},
        {"number": "202", "floor": 2, "room_type": "deluxe", "price": "210.00", "capacity": 3},
        {"number": "301", "floor": 3, "room_type": "suite", "price": "400.00", "capacity": 4},
        {"number": "302", "floor": 3, "room_type": "suite", "price": "420.00", "capacity": 4},
        {"number": "401", "floor": 4, "room_type": "penthouse", "price": "800.00", "capacity": 6},
    ]

    AMENITIES = {
        "standard": ["wifi", "tv", "ac", "phone"],
        "deluxe": ["wifi", "tv", "ac", "phone", "minibar", "safe", "bathrobe"],
        "suite": ["wifi", "tv", "ac", "phone", "minibar", "safe", "bathrobe", "jacuzzi", "lounge"],
        "penthouse": ["wifi", "tv", "ac", "phone", "minibar", "safe", "bathrobe", "jacuzzi", "lounge", "butler", "terrace"],
    }

    def handle(self, *args, **options):
        self.stdout.write("🌱 Seeding demo data...")

        with transaction.atomic():
            self._create_rooms()
            self._create_users()
            self._create_bookings()

        self.stdout.write(self.style.SUCCESS("✅ Demo data seeded successfully!"))
        self.stdout.write("\nDemo credentials:")
        self.stdout.write("  Guest:   guest@demo.com / Demo1234!")
        self.stdout.write("  Staff:   staff@demo.com / Demo1234!")
        self.stdout.write("  Manager: manager@demo.com / Demo1234!")
        self.stdout.write("  Admin:   admin@demo.com / Demo1234!")

    def _create_rooms(self):
        from hotel_agent.core.models import Room
        for data in self.ROOM_DATA:
            room, created = Room.objects.get_or_create(
                number=data["number"],
                defaults={
                    "floor": data["floor"],
                    "room_type": data["room_type"],
                    "price_per_night": data["price"],
                    "capacity": data["capacity"],
                    "amenities": self.AMENITIES.get(data["room_type"], []),
                    "description": f"Beautiful {data['room_type'].title()} room on floor {data['floor']}",
                    "status": "available",
                    "is_active": True,
                }
            )
            status = "Created" if created else "Exists"
            self.stdout.write(f"  Room {data['number']}: {status}")

    def _create_users(self):
        from hotel_agent.core.models import User
        users = [
            {"email": "guest@demo.com", "role": "guest", "first_name": "Alice", "last_name": "Smith"},
            {"email": "staff@demo.com", "role": "staff", "first_name": "Bob", "last_name": "Jones"},
            {"email": "manager@demo.com", "role": "manager", "first_name": "Carol", "last_name": "Williams"},
            {"email": "admin@demo.com", "role": "admin", "first_name": "Dave", "last_name": "Brown", "is_staff": True, "is_superuser": True},
        ]
        for u in users:
            is_staff = u.pop("is_staff", False)
            is_superuser = u.pop("is_superuser", False)
            user, created = User.objects.get_or_create(email=u["email"], defaults=u)
            if created:
                user.set_password("Demo1234!")
                user.is_staff = is_staff
                user.is_superuser = is_superuser
                user.save()
                self.stdout.write(f"  User {u['email']}: Created")
            else:
                self.stdout.write(f"  User {u['email']}: Exists")

    def _create_bookings(self):
        from hotel_agent.core.models import User, Room, Booking
        try:
            guest = User.objects.get(email="guest@demo.com")
            room = Room.objects.get(number="201")

            booking, created = Booking.objects.get_or_create(
                guest=guest,
                room=room,
                check_in=date.today() - timedelta(days=1),
                defaults={
                    "check_out": date.today() + timedelta(days=2),
                    "adults": 2,
                    "total_price": "600.00",
                    "status": "checked_in",
                    "special_requests": "Extra pillows please",
                }
            )
            if created:
                room.status = "occupied"
                room.save()
                self.stdout.write(f"  Booking {booking.confirmation_code}: Created (guest checked in to Room 201)")
            else:
                self.stdout.write(f"  Booking: Exists")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Booking creation skipped: {e}"))
