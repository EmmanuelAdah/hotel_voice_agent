"""
Kafka event handlers for Hotel Voice Agent.
Each handler processes specific event types from Kafka topics.
"""
import logging
from django.apps import apps

logger = logging.getLogger("hotel_agent.kafka.handlers")


def handle_service_request_created(event: dict):
    """Process new service request event - notify staff via channels."""
    payload = event.get("payload", {})
    request_id = payload.get("request_id")
    service_type = payload.get("service_type")
    priority = payload.get("priority")

    logger.info("processing_service_request", extra={
        "request_id": request_id,
        "service_type": service_type,
        "priority": priority,
    })

    # Import here to avoid circular imports at module level
    from hotel_agent.core.tasks import notify_staff_of_service_request
    notify_staff_of_service_request.delay(request_id, priority)


def handle_voice_session_completed(event: dict):
    """Persist voice session analytics and update usage metrics."""
    payload = event.get("payload", {})
    session_id = payload.get("session_id")
    tokens = payload.get("tokens_used", 0)
    duration = payload.get("duration_seconds", 0)

    logger.info("voice_session_completed_handler", extra={
        "session_id": session_id, "tokens": tokens, "duration_s": duration
    })

    from hotel_agent.core.tasks import process_session_analytics
    process_session_analytics.delay(session_id)


def handle_notification(event: dict):
    """Push notifications to guests via WebSocket channels."""
    payload = event.get("payload", {})
    guest_id = payload.get("guest_id")
    message = payload.get("message")
    channel = payload.get("channel", "ws")

    if channel == "ws":
        from hotel_agent.api.consumers import push_notification_to_guest
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            push_notification_to_guest(guest_id, message, payload.get("data", {}))
        )
    elif channel == "email":
        from hotel_agent.core.tasks import send_notification_email
        send_notification_email.delay(guest_id, message)


def handle_audit_log(event: dict):
    """Persist audit log events to database."""
    from hotel_agent.core.models import AuditLog
    payload = event.get("payload", {})
    try:
        AuditLog.objects.create(
            action=payload.get("action", "unknown"),
            resource_type=payload.get("resource_type", ""),
            resource_id=payload.get("resource_id", ""),
            changes=payload.get("changes", {}),
            ip_address=payload.get("ip_address"),
        )
    except Exception as e:
        logger.error("audit_log_persist_error", extra={"error": str(e)})


def register_all_handlers(consumer):
    """Register all handlers with a KafkaConsumerService instance."""
    consumer.register_handler("service.request.created", handle_service_request_created)
    consumer.register_handler("voice.session.completed", handle_voice_session_completed)
    consumer.register_handler("notification", handle_notification)
    consumer.register_handler("audit.log", handle_audit_log)
    logger.info("all_kafka_handlers_registered")
