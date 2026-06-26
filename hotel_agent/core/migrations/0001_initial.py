"""
Initial migration for Hotel Voice Agent core models.
"""
from django.db import migrations, models
import django.contrib.auth.models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("is_superuser", models.BooleanField(default=False)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("email", models.EmailField(db_index=True, max_length=254, unique=True)),
                ("first_name", models.CharField(blank=True, max_length=150)),
                ("last_name", models.CharField(blank=True, max_length=150)),
                ("phone", models.CharField(blank=True, db_index=True, max_length=20)),
                ("role", models.CharField(
                    choices=[("guest","Guest"),("staff","Staff"),("manager","Manager"),("admin","Admin")],
                    db_index=True, default="guest", max_length=20
                )),
                ("is_active", models.BooleanField(default=True)),
                ("is_staff", models.BooleanField(default=False)),
                ("last_login_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("preferences", models.JSONField(blank=True, default=dict)),
                ("failed_login_attempts", models.PositiveSmallIntegerField(default=0)),
                ("locked_until", models.DateTimeField(blank=True, null=True)),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("groups", models.ManyToManyField(blank=True, related_name="user_set", to="auth.group")),
                ("user_permissions", models.ManyToManyField(blank=True, related_name="user_set", to="auth.permission")),
            ],
            options={"db_table": "core_users", "ordering": ["-created_at"], "verbose_name": "User"},
            managers=[("objects", django.contrib.auth.models.BaseUserManager())],
        ),
        migrations.CreateModel(
            name="Room",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("number", models.CharField(max_length=10, unique=True)),
                ("floor", models.PositiveSmallIntegerField()),
                ("room_type", models.CharField(
                    choices=[("standard","Standard"),("deluxe","Deluxe"),("suite","Suite"),("penthouse","Penthouse")],
                    db_index=True, max_length=20
                )),
                ("status", models.CharField(
                    choices=[("available","Available"),("occupied","Occupied"),("maintenance","Maintenance"),("cleaning","Cleaning")],
                    db_index=True, default="available", max_length=20
                )),
                ("capacity", models.PositiveSmallIntegerField(default=2)),
                ("price_per_night", models.DecimalField(decimal_places=2, max_digits=10)),
                ("amenities", models.JSONField(default=list)),
                ("description", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"db_table": "core_rooms", "ordering": ["floor", "number"]},
        ),
        migrations.AddIndex(
            model_name="user",
            index=models.Index(fields=["email", "is_active"], name="idx_user_email_active"),
        ),
        migrations.AddIndex(
            model_name="user",
            index=models.Index(fields=["role", "is_active"], name="idx_user_role_active"),
        ),
        migrations.AddIndex(
            model_name="room",
            index=models.Index(fields=["status", "room_type", "is_active"], name="idx_room_status_type"),
        ),
        migrations.AddIndex(
            model_name="room",
            index=models.Index(fields=["floor", "status"], name="idx_room_floor_status"),
        ),
    ]
