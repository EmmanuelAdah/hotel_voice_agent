"""
Django signals for Hotel Voice Agent.
Handles audit logging, cache invalidation, and Kafka event publishing.
"""
import logging
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.core.cache import cache

logger = logging.getLogger("hotel_agent.signals")


@receiver(post_save, sender="core.ServiceRequest")
def on_service_request_save(sender, instance, created, **kwargs):
    """Publish Kafka event and invalidate caches on service request change."""
    from hotel_agent.kafka.producer_consumer import KafkaProducerService, ServiceRequestEvent
    producer = KafkaProducerService()

    if created:
        producer.publish(
            "SERVICE_REQUESTS",
            ServiceRequestEvent.created(
                str(instance.id),
                instance.service_type,
                instance.priority,
                str(instance.guest_id),
            ),
            key=str(instance.guest_id),
        )
        # Invalidate staff dashboard cache
        cache.delete_pattern("staff_dashboard:*")
    else:
        # Update metrics gauge for status changes
        from hotel_agent.monitoring.metrics import SERVICE_REQUEST_STATUS
        from hotel_agent.core.models import ServiceRequest
        for s in ServiceRequest.Status:
            count = ServiceRequest.objects.filter(status=s.value).count()
            SERVICE_REQUEST_STATUS.labels(status=s.value).set(count)


@receiver(post_save, sender="core.Room")
def on_room_save(sender, instance, **kwargs):
    """Invalidate room availability cache on room status change."""
    cache.delete("available_rooms")
    cache.delete(f"room:{instance.id}")


@receiver(post_save, sender="core.Booking")
def on_booking_save(sender, instance, created, **kwargs):
    """Publish audit event and update room status on booking change."""
    from hotel_agent.kafka.producer_consumer import KafkaProducerService, KafkaEvent
    producer = KafkaProducerService()

    if created:
        event = KafkaEvent(
            event_type="booking.created",
            payload={
                "booking_id": str(instance.id),
                "guest_id": str(instance.guest_id),
                "room_id": str(instance.room_id),
                "check_in": str(instance.check_in),
                "check_out": str(instance.check_out),
            }
        )
        producer.publish("AUDIT_LOG", event)

    # Sync room status with booking status
    from hotel_agent.core.models import Room
    if instance.status == "checked_in":
        Room.objects.filter(id=instance.room_id).update(status=Room.Status.OCCUPIED)
        cache.delete("available_rooms")
    elif instance.status in ("checked_out", "cancelled"):
        Room.objects.filter(id=instance.room_id).update(status=Room.Status.CLEANING)
        cache.delete("available_rooms")


@receiver(post_save, sender="core.User")
def on_user_save(sender, instance, created, **kwargs):
    """Invalidate user cache on profile update."""
    cache.delete(f"user:{instance.id}")
    cache.delete(f"user:email:{instance.email}")
