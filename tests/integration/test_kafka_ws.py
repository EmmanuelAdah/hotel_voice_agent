"""
Integration tests for Kafka producer/consumer and WebSocket consumers.
"""
import json
import uuid
from unittest.mock import MagicMock, patch, call
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model

from hotel_agent.kafka.producer_consumer import (
    KafkaEvent, VoiceSessionEvent, ServiceRequestEvent, NotificationEvent
)
from hotel_agent.kafka.handlers import (
    handle_service_request_created,
    handle_voice_session_completed,
    handle_audit_log,
)

User = get_user_model()


class KafkaEventSchemaTest(TestCase):
    """Validate Kafka event serialization."""

    def test_kafka_event_serializes_to_json(self):
        event = KafkaEvent(event_type="test.event", payload={"key": "value"})
        data = json.loads(event.to_json())
        self.assertEqual(data["event_type"], "test.event")
        self.assertEqual(data["payload"]["key"], "value")
        self.assertIn("event_id", data)
        self.assertIn("timestamp", data)
        self.assertEqual(data["schema_version"], "1.0")

    def test_voice_session_started_event(self):
        event = VoiceSessionEvent.started("sess-1", "guest-1", "302")
        data = json.loads(event.to_json())
        self.assertEqual(data["event_type"], "voice.session")
        self.assertEqual(data["payload"]["action"], "started")
        self.assertEqual(data["payload"]["room_number"], "302")

    def test_voice_session_completed_event(self):
        event = VoiceSessionEvent.completed("sess-1", 120, 500)
        data = json.loads(event.to_json())
        self.assertEqual(data["payload"]["duration_seconds"], 120)
        self.assertEqual(data["payload"]["tokens_used"], 500)

    def test_service_request_created_event(self):
        event = ServiceRequestEvent.created("req-1", "room_service", "high", "guest-1")
        data = json.loads(event.to_json())
        self.assertEqual(data["event_type"], "service.request")
        self.assertEqual(data["payload"]["service_type"], "room_service")

    def test_notification_event(self):
        event = NotificationEvent.guest_notification(
            "guest-1", "ws", "Your room is ready", {"room": "302"}
        )
        data = json.loads(event.to_json())
        self.assertEqual(data["payload"]["channel"], "ws")
        self.assertIn("data", data["payload"])


class KafkaProducerTest(TestCase):
    """Test KafkaProducerService with mocked confluent-kafka Producer."""

    @patch("hotel_agent.kafka.producer_consumer.Producer")
    def test_publish_calls_produce(self, MockProducer):
        from hotel_agent.kafka.producer_consumer import KafkaProducerService
        mock_instance = MockProducer.return_value
        producer = KafkaProducerService()
        event = KafkaEvent(event_type="test", payload={})

        result = producer.publish("VOICE_SESSIONS", event)

        self.assertTrue(result)
        mock_instance.produce.assert_called_once()
        kwargs = mock_instance.produce.call_args[1]
        self.assertIn("hotel.voice.sessions", kwargs.get("topic", ""))

    @patch("hotel_agent.kafka.producer_consumer.Producer")
    def test_publish_unknown_topic_returns_false(self, MockProducer):
        from hotel_agent.kafka.producer_consumer import KafkaProducerService
        producer = KafkaProducerService()
        event = KafkaEvent(event_type="test", payload={})
        result = producer.publish("NONEXISTENT_TOPIC", event)
        self.assertFalse(result)


class KafkaHandlerTest(TestCase):
    """Test Kafka event handlers."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="handler_test@hotel.com",
            password="Pass123!",
            role=User.Role.GUEST,
        )

    @patch("hotel_agent.kafka.handlers.notify_staff_of_service_request")
    def test_handle_service_request_created(self, mock_task):
        event = {
            "event_type": "service.request.created",
            "payload": {
                "request_id": str(uuid.uuid4()),
                "service_type": "housekeeping",
                "priority": "high",
                "guest_id": str(self.user.id),
            }
        }
        handle_service_request_created(event)
        mock_task.delay.assert_called_once()

    @patch("hotel_agent.kafka.handlers.process_session_analytics")
    def test_handle_voice_session_completed(self, mock_task):
        event = {
            "event_type": "voice.session.completed",
            "payload": {
                "session_id": str(uuid.uuid4()),
                "tokens_used": 350,
                "duration_seconds": 90,
            }
        }
        handle_voice_session_completed(event)
        mock_task.delay.assert_called_once()

    def test_handle_audit_log_persists(self):
        from hotel_agent.core.models import AuditLog
        event = {
            "event_type": "audit.log",
            "payload": {
                "action": "test.action",
                "resource_type": "booking",
                "resource_id": str(uuid.uuid4()),
                "changes": {"status": "confirmed"},
                "ip_address": "192.168.1.1",
            }
        }
        count_before = AuditLog.objects.count()
        handle_audit_log(event)
        self.assertEqual(AuditLog.objects.count(), count_before + 1)
        log = AuditLog.objects.latest("timestamp")
        self.assertEqual(log.action, "test.action")


class KafkaConsumerRetryTest(TestCase):
    """Test consumer retry and DLQ behavior."""

    @patch("hotel_agent.kafka.producer_consumer.Producer")
    @patch("hotel_agent.kafka.producer_consumer.Consumer")
    def test_consumer_sends_to_dlq_after_max_retries(self, MockConsumer, MockProducer):
        from hotel_agent.kafka.producer_consumer import KafkaConsumerService

        consumer = KafkaConsumerService(topics=["hotel.voice.sessions"])
        fail_count = [0]

        def failing_handler(event):
            fail_count[0] += 1
            raise RuntimeError("Simulated failure")

        consumer.register_handler("voice.session", failing_handler)

        # Simulate processing a message
        mock_msg = MagicMock()
        mock_msg.value.return_value = json.dumps({
            "event_type": "voice.session",
            "payload": {},
        }).encode()
        mock_msg.error.return_value = None
        mock_msg.topic.return_value = "hotel.voice.sessions"
        mock_msg.partition.return_value = 0
        mock_msg.offset.return_value = 42

        with patch.object(consumer, "_send_to_dlq") as mock_dlq:
            consumer._process_message(mock_msg)
            mock_dlq.assert_called_once()

        self.assertEqual(fail_count[0], KafkaConsumerService.MAX_RETRIES)


class WebSocketConsumerTest(TestCase):
    """Test WebSocket consumer authentication."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="ws_test@hotel.com",
            password="Pass123!",
            role=User.Role.GUEST,
        )

    def test_authenticate_token_valid(self):
        from rest_framework_simplejwt.tokens import AccessToken
        from hotel_agent.api.consumers import VoiceSessionConsumer
        from asgiref.sync import async_to_sync

        token = str(AccessToken.for_user(self.user))
        consumer = VoiceSessionConsumer()
        result = async_to_sync(consumer._authenticate_token)(token)
        self.assertEqual(result.id, self.user.id)

    def test_authenticate_token_invalid(self):
        from hotel_agent.api.consumers import VoiceSessionConsumer
        from django.contrib.auth.models import AnonymousUser
        from asgiref.sync import async_to_sync

        consumer = VoiceSessionConsumer()
        result = async_to_sync(consumer._authenticate_token)("invalid-token")
        self.assertIsInstance(result, AnonymousUser)
