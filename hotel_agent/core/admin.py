"""Django Admin configuration for Hotel Voice Agent."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from hotel_agent.core.models import (
    User, Room, Booking, ServiceRequest, VoiceSession, AuditLog
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["-created_at"]
    list_display = ["email", "full_name", "role", "is_active", "created_at"]
    list_filter = ["role", "is_active", "is_staff"]
    search_fields = ["email", "first_name", "last_name", "phone"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal Info", {"fields": ("first_name", "last_name", "phone")}),
        ("Role & Permissions", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups")}),
        ("Security", {"fields": ("last_login_ip", "failed_login_attempts", "locked_until")}),
        ("Preferences", {"fields": ("preferences",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2", "role", "first_name", "last_name"),
        }),
    )
    readonly_fields = ["created_at", "updated_at", "last_login_ip", "failed_login_attempts"]


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ["number", "floor", "room_type", "status", "capacity", "price_per_night", "is_active"]
    list_filter = ["room_type", "status", "floor", "is_active"]
    search_fields = ["number", "description"]
    list_editable = ["status", "is_active"]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["confirmation_code", "guest_email", "room_number", "check_in", "check_out", "status", "total_price"]
    list_filter = ["status", "room__room_type", "check_in"]
    search_fields = ["confirmation_code", "guest__email", "guest__first_name"]
    raw_id_fields = ["guest", "room"]
    readonly_fields = ["confirmation_code", "created_at", "updated_at"]

    @admin.display(description="Guest Email")
    def guest_email(self, obj):
        return obj.guest.email

    @admin.display(description="Room")
    def room_number(self, obj):
        return obj.room.number


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = [
        "id_short", "service_type", "priority_badge", "status",
        "guest_email", "room_number", "assigned_to_name", "created_at"
    ]
    list_filter = ["service_type", "priority", "status"]
    search_fields = ["guest__email", "booking__confirmation_code", "description"]
    raw_id_fields = ["guest", "booking", "assigned_to"]
    readonly_fields = ["voice_session_id", "kafka_event_id", "created_at"]

    @admin.display(description="ID")
    def id_short(self, obj):
        return str(obj.id)[:8]

    @admin.display(description="Priority")
    def priority_badge(self, obj):
        colors = {"urgent": "red", "high": "orange", "normal": "green", "low": "gray"}
        color = colors.get(obj.priority, "gray")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_priority_display()
        )

    @admin.display(description="Guest")
    def guest_email(self, obj):
        return obj.guest.email

    @admin.display(description="Room")
    def room_number(self, obj):
        return obj.booking.room.number if obj.booking else "—"

    @admin.display(description="Assigned To")
    def assigned_to_name(self, obj):
        return obj.assigned_to.full_name if obj.assigned_to else "Unassigned"


@admin.register(VoiceSession)
class VoiceSessionAdmin(admin.ModelAdmin):
    list_display = ["id", "guest_email", "status", "started_at", "duration_seconds", "tokens_used"]
    list_filter = ["status"]
    search_fields = ["guest__email", "id"]
    readonly_fields = ["transcript", "tokens_used", "tts_characters", "started_at", "ended_at"]

    @admin.display(description="Guest")
    def guest_email(self, obj):
        return obj.guest.email


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "user_email", "action", "resource_type", "resource_id", "ip_address"]
    list_filter = ["action", "resource_type"]
    search_fields = ["user__email", "action", "resource_id"]
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="User")
    def user_email(self, obj):
        return obj.user.email if obj.user else "—"
