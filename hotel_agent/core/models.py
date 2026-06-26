"""
Core models for Hotel Voice Agent.
Includes custom User, Room, Booking, ServiceRequest with optimized indexes.
"""
import uuid
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TimestampedModel(models.Model):
    """Abstract base model with created/updated timestamps."""
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(TimestampedModel):
    """Abstract base model with UUID primary key."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


# ── User ──────────────────────────────────────────────────────────────────────

class UserManager(BaseUserManager):
    def create_user(self, email: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, UUIDModel):
    class Role(models.TextChoices):
        GUEST = "guest", _("Guest")
        STAFF = "staff", _("Staff")
        MANAGER = "manager", _("Manager")
        ADMIN = "admin", _("Admin")

    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True, db_index=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.GUEST, db_index=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    preferences = models.JSONField(default=dict, blank=True)
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta:
        db_table = "core_users"
        indexes = [
            models.Index(fields=["email", "is_active"], name="idx_user_email_active"),
            models.Index(fields=["role", "is_active"], name="idx_user_role_active"),
        ]
        verbose_name = _("User")
        verbose_name_plural = _("Users")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or self.email

    def is_locked(self) -> bool:
        if self.locked_until and self.locked_until > timezone.now():
            return True
        return False

    def record_failed_login(self):
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= 5:
            self.locked_until = timezone.now() + timezone.timedelta(minutes=30)
        self.save(update_fields=["failed_login_attempts", "locked_until"])

    def reset_failed_login(self):
        if self.failed_login_attempts > 0:
            self.failed_login_attempts = 0
            self.locked_until = None
            self.save(update_fields=["failed_login_attempts", "locked_until"])


# ── Room ──────────────────────────────────────────────────────────────────────

class Room(UUIDModel):
    class RoomType(models.TextChoices):
        STANDARD = "standard", _("Standard")
        DELUXE = "deluxe", _("Deluxe")
        SUITE = "suite", _("Suite")
        PENTHOUSE = "penthouse", _("Penthouse")

    class Status(models.TextChoices):
        AVAILABLE = "available", _("Available")
        OCCUPIED = "occupied", _("Occupied")
        MAINTENANCE = "maintenance", _("Maintenance")
        CLEANING = "cleaning", _("Cleaning")

    number = models.CharField(max_length=10, unique=True)
    floor = models.PositiveSmallIntegerField()
    room_type = models.CharField(max_length=20, choices=RoomType.choices, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE, db_index=True)
    capacity = models.PositiveSmallIntegerField(default=2)
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2)
    amenities = models.JSONField(default=list)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "core_rooms"
        indexes = [
            models.Index(fields=["status", "room_type", "is_active"], name="idx_room_status_type"),
            models.Index(fields=["floor", "status"], name="idx_room_floor_status"),
        ]
        ordering = ["floor", "number"]

    def __str__(self) -> str:
        return f"Room {self.number} ({self.get_room_type_display()})"


# ── Booking ───────────────────────────────────────────────────────────────────

class Booking(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        CONFIRMED = "confirmed", _("Confirmed")
        CHECKED_IN = "checked_in", _("Checked In")
        CHECKED_OUT = "checked_out", _("Checked Out")
        CANCELLED = "cancelled", _("Cancelled")

    guest = models.ForeignKey(User, on_delete=models.PROTECT, related_name="bookings", db_index=True)
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="bookings")
    check_in = models.DateField(db_index=True)
    check_out = models.DateField(db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    adults = models.PositiveSmallIntegerField(default=1)
    children = models.PositiveSmallIntegerField(default=0)
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    special_requests = models.TextField(blank=True)
    confirmation_code = models.CharField(max_length=12, unique=True, db_index=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "core_bookings"
        indexes = [
            models.Index(fields=["guest", "status"], name="idx_booking_guest_status"),
            models.Index(fields=["room", "check_in", "check_out"], name="idx_booking_room_dates"),
            models.Index(fields=["check_in", "check_out", "status"], name="idx_booking_dates_status"),
            models.Index(fields=["confirmation_code"], name="idx_booking_confirmation"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(check_out__gt=models.F("check_in")),
                name="check_out_after_check_in",
            )
        ]

    def __str__(self) -> str:
        return f"Booking {self.confirmation_code} - {self.guest.email}"

    def save(self, *args, **kwargs):
        if not self.confirmation_code:
            import secrets, string
            alphabet = string.ascii_uppercase + string.digits
            self.confirmation_code = "".join(secrets.choice(alphabet) for _ in range(12))
        super().save(*args, **kwargs)


# ── Service Request ───────────────────────────────────────────────────────────

class ServiceRequest(UUIDModel):
    class ServiceType(models.TextChoices):
        ROOM_SERVICE = "room_service", _("Room Service")
        HOUSEKEEPING = "housekeeping", _("Housekeeping")
        MAINTENANCE = "maintenance", _("Maintenance")
        CONCIERGE = "concierge", _("Concierge")
        WAKE_UP_CALL = "wake_up_call", _("Wake Up Call")
        TRANSPORT = "transport", _("Transport")
        SPA = "spa", _("Spa")
        DINING = "dining", _("Dining Reservation")
        LAUNDRY = "laundry", _("Laundry")
        OTHER = "other", _("Other")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("High")
        URGENT = "urgent", _("Urgent")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ASSIGNED = "assigned", _("Assigned")
        IN_PROGRESS = "in_progress", _("In Progress")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="service_requests")
    guest = models.ForeignKey(User, on_delete=models.PROTECT, related_name="service_requests")
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_requests", db_index=True
    )
    service_type = models.CharField(max_length=30, choices=ServiceType.choices, db_index=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    description = models.TextField()
    notes = models.TextField(blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    voice_session_id = models.UUIDField(null=True, blank=True, db_index=True)
    kafka_event_id = models.CharField(max_length=100, blank=True, db_index=True)

    class Meta:
        db_table = "core_service_requests"
        indexes = [
            models.Index(fields=["status", "priority", "service_type"], name="idx_sr_status_priority"),
            models.Index(fields=["guest", "status", "created_at"], name="idx_sr_guest_status"),
            models.Index(fields=["assigned_to", "status"], name="idx_sr_assigned_status"),
            models.Index(fields=["created_at", "service_type"], name="idx_sr_created_type"),
        ]
        ordering = ["-priority", "-created_at"]

    def __str__(self) -> str:
        return f"{self.get_service_type_display()} - {self.booking.confirmation_code}"


# ── Voice Session ─────────────────────────────────────────────────────────────

class VoiceSession(UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")
        TIMEOUT = "timeout", _("Timeout")

    guest = models.ForeignKey(User, on_delete=models.PROTECT, related_name="voice_sessions")
    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, null=True, blank=True, related_name="voice_sessions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    transcript = models.JSONField(default=list)  # List of {role, content, timestamp}
    intent_detected = models.CharField(max_length=100, blank=True)
    service_requests_created = models.ManyToManyField(ServiceRequest, blank=True)
    tokens_used = models.PositiveIntegerField(default=0)
    tts_characters = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    channel_name = models.CharField(max_length=255, blank=True, db_index=True)

    class Meta:
        db_table = "core_voice_sessions"
        indexes = [
            models.Index(fields=["guest", "status", "started_at"], name="idx_vs_guest_status"),
            models.Index(fields=["status", "started_at"], name="idx_vs_status_started"),
        ]
        ordering = ["-started_at"]


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=50, db_index=True)
    resource_id = models.CharField(max_length=100, blank=True)
    changes = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    kafka_offset = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "core_audit_logs"
        indexes = [
            models.Index(fields=["user", "timestamp"], name="idx_audit_user_ts"),
            models.Index(fields=["resource_type", "resource_id"], name="idx_audit_resource"),
            models.Index(fields=["action", "timestamp"], name="idx_audit_action_ts"),
        ]
        ordering = ["-timestamp"]
