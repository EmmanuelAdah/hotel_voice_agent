"""Celery tasks for Hotel Voice Agent."""
import logging
from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from django.db import transaction

logger = logging.getLogger("hotel_agent.tasks")


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def notify_staff_of_service_request(self, request_id: str, priority: str):
    """Notify staff of a new service request via WebSocket."""
    try:
        from hotel_agent.core.models import ServiceRequest
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        sr = ServiceRequest.objects.select_related("booking__room", "guest").get(id=request_id)
        channel_layer = get_channel_layer()

        message = {
            "type": "notification_message",
            "message": f"New {sr.get_service_type_display()} request - Room {sr.booking.room.number}",
            "data": {
                "request_id": str(sr.id),
                "service_type": sr.service_type,
                "priority": priority,
                "room": sr.booking.room.number,
                "guest": sr.guest.full_name,
            },
        }
        async_to_sync(channel_layer.group_send)("staff_notifications", message)
        logger.info("staff_notified", extra={"request_id": request_id})

    except Exception as exc:
        logger.error("notify_staff_failed", extra={"request_id": request_id, "error": str(exc)})
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2)
def process_session_analytics(self, session_id: str):
    """Process and store voice session analytics."""
    try:
        from hotel_agent.core.models import VoiceSession
        session = VoiceSession.objects.get(id=session_id)
        turns = len([m for m in session.transcript if m.get("role") == "user"])

        cache.set(
            f"session_analytics:{session_id}",
            {
                "turns": turns,
                "tokens": session.tokens_used,
                "duration": session.duration_seconds,
                "tts_chars": session.tts_characters,
            },
            timeout=86400,
        )
        logger.info("session_analytics_processed", extra={"session_id": session_id, "turns": turns})

    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task
def cleanup_expired_sessions():
    """Mark stale ACTIVE sessions as TIMEOUT."""
    from hotel_agent.core.models import VoiceSession
    cutoff = timezone.now() - timezone.timedelta(hours=2)
    updated = VoiceSession.objects.filter(
        status=VoiceSession.Status.ACTIVE,
        started_at__lt=cutoff,
    ).update(status=VoiceSession.Status.TIMEOUT, ended_at=timezone.now())
    logger.info("expired_sessions_cleaned", extra={"count": updated})


@shared_task
def sync_room_availability():
    """Refresh room availability cache."""
    from hotel_agent.core.models import Room
    rooms = Room.objects.filter(is_active=True).values("id", "number", "room_type", "status", "price_per_night")
    cache.set("available_rooms", list(rooms), timeout=300)
    logger.info("room_availability_synced", extra={"count": len(rooms)})


@shared_task(bind=True, max_retries=3)
def send_notification_email(self, guest_id: str, message: str):
    """Send email notification to a guest."""
    try:
        from hotel_agent.core.models import User
        from django.core.mail import send_mail
        guest = User.objects.get(id=guest_id)
        send_mail(
            subject="Hotel Service Update",
            message=message,
            from_email="noreply@hotel.com",
            recipient_list=[guest.email],
            fail_silently=False,
        )
        logger.info("email_sent", extra={"guest_id": guest_id})
    except Exception as exc:
        raise self.retry(exc=exc)
