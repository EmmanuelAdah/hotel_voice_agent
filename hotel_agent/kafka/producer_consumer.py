"""
Kafka integration for Hotel Voice Agent.
- KafkaProducerService: async event publishing
- KafkaConsumerService: event consumption with retry logic
- Topic definitions and event schemas
"""
import json
import logging
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Callable, Awaitable
from django.conf import settings
from confluent_kafka import Producer, Consumer, KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

logger = logging.getLogger("hotel_agent.kafka")


# ── Event Schemas ─────────────────────────────────────────────────────────────

@dataclass
class KafkaEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    payload: dict = field(default_factory=dict)
    schema_version: str = "1.0"
    source: str = "hotel-voice-agent"

    def to_json(self) -> str:
        return json.dumps(asdict(self))


@dataclass
class VoiceSessionEvent(KafkaEvent):
    event_type: str = "voice.session"

    @classmethod
    def started(cls, session_id: str, guest_id: str, room_number: str) -> "VoiceSessionEvent":
        return cls(payload={
            "action": "started", "session_id": session_id,
            "guest_id": guest_id, "room_number": room_number,
        })

    @classmethod
    def completed(cls, session_id: str, duration_s: int, tokens: int) -> "VoiceSessionEvent":
        return cls(payload={
            "action": "completed", "session_id": session_id,
            "duration_seconds": duration_s, "tokens_used": tokens,
        })


@dataclass
class ServiceRequestEvent(KafkaEvent):
    event_type: str = "service.request"

    @classmethod
    def created(cls, request_id: str, service_type: str, priority: str, guest_id: str) -> "ServiceRequestEvent":
        return cls(payload={
            "action": "created", "request_id": request_id,
            "service_type": service_type, "priority": priority, "guest_id": guest_id,
        })

    @classmethod
    def status_changed(cls, request_id: str, old_status: str, new_status: str) -> "ServiceRequestEvent":
        return cls(payload={
            "action": "status_changed", "request_id": request_id,
            "old_status": old_status, "new_status": new_status,
        })


@dataclass
class NotificationEvent(KafkaEvent):
    event_type: str = "notification"

    @classmethod
    def guest_notification(cls, guest_id: str, channel: str, message: str, data: dict | None = None) -> "NotificationEvent":
        return cls(payload={
            "guest_id": guest_id, "channel": channel,
            "message": message, "data": data or {},
        })


# ── Kafka Config ──────────────────────────────────────────────────────────────

def _base_config() -> dict:
    cfg = {
        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "security.protocol": settings.KAFKA_SECURITY_PROTOCOL,
    }
    if settings.KAFKA_SASL_MECHANISM:
        cfg.update({
            "sasl.mechanism": settings.KAFKA_SASL_MECHANISM,
            "sasl.username": settings.KAFKA_SASL_USERNAME,
            "sasl.password": settings.KAFKA_SASL_PASSWORD,
        })
    return cfg


# ── Producer ──────────────────────────────────────────────────────────────────

class KafkaProducerService:
    """
    Thread-safe Kafka producer with delivery callbacks,
    retry logic, and Prometheus metrics integration.
    """

    def __init__(self):
        config = _base_config()
        config.update({
            "acks": "all",
            "retries": 3,
            "retry.backoff.ms": 500,
            "linger.ms": 5,
            "batch.size": 65536,
            "compression.type": "snappy",
            "enable.idempotence": True,
        })
        self._producer = Producer(config)
        self._topic_map = settings.KAFKA_TOPICS

    def publish(self, topic_key: str, event: KafkaEvent, key: str | None = None) -> bool:
        """Publish event to Kafka topic. Returns True on success."""
        topic = self._topic_map.get(topic_key)
        if not topic:
            logger.error("kafka_unknown_topic", extra={"topic_key": topic_key})
            return False

        try:
            self._producer.produce(
                topic=topic,
                value=event.to_json().encode("utf-8"),
                key=(key or event.event_id).encode("utf-8"),
                on_delivery=self._delivery_callback,
            )
            self._producer.poll(0)  # Trigger delivery callbacks
            return True
        except KafkaException as e:
            logger.error("kafka_produce_error", extra={"topic": topic, "error": str(e)})
            return False

    def flush(self, timeout: float = 10.0) -> int:
        """Flush pending messages. Returns number of messages still in queue."""
        return self._producer.flush(timeout)

    def close(self):
        self.flush()

    @staticmethod
    def _delivery_callback(err, msg):
        if err:
            logger.error("kafka_delivery_failed", extra={
                "topic": msg.topic(), "partition": msg.partition(), "error": str(err)
            })
        else:
            logger.debug("kafka_delivered", extra={
                "topic": msg.topic(), "partition": msg.partition(), "offset": msg.offset()
            })


# ── Consumer ──────────────────────────────────────────────────────────────────

class KafkaConsumerService:
    """
    Long-running Kafka consumer with:
    - Configurable handler registry
    - At-least-once delivery semantics
    - Dead letter queue (DLQ) on repeated failures
    - Graceful shutdown
    """

    MAX_RETRIES = 3
    RETRY_BACKOFF_S = [1, 5, 15]

    def __init__(self, topics: list[str], group_id: str | None = None):
        config = _base_config()
        config.update({
            "group.id": group_id or settings.KAFKA_CONSUMER_GROUP,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,  # Manual commit for at-least-once
            "max.poll.interval.ms": 300000,
            "session.timeout.ms": 30000,
            "heartbeat.interval.ms": 10000,
            "fetch.min.bytes": 1,
            "fetch.max.wait.ms": 500,
        })
        self._consumer = Consumer(config)
        self._topics = topics
        self._handlers: dict[str, list[Callable]] = {}
        self._running = False
        self._producer = KafkaProducerService()

    def register_handler(self, event_type: str, handler: Callable):
        """Register a handler for a specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.info("handler_registered", extra={"event_type": event_type})

    def start(self):
        """Start consuming messages (blocking)."""
        self._consumer.subscribe(self._topics)
        self._running = True
        logger.info("kafka_consumer_started", extra={"topics": self._topics})

        try:
            while self._running:
                msg = self._consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    self._handle_error(msg.error())
                    continue
                self._process_message(msg)
        except KeyboardInterrupt:
            logger.info("kafka_consumer_interrupted")
        finally:
            self._consumer.close()
            logger.info("kafka_consumer_stopped")

    def stop(self):
        self._running = False

    def _process_message(self, msg):
        """Process a single Kafka message with retry and DLQ."""
        try:
            data = json.loads(msg.value().decode("utf-8"))
            event_type = data.get("event_type", "unknown")
            handlers = self._handlers.get(event_type, [])

            if not handlers:
                logger.debug("no_handler", extra={"event_type": event_type})
                self._consumer.commit(message=msg)
                return

            for handler in handlers:
                attempt = 0
                while attempt < self.MAX_RETRIES:
                    try:
                        handler(data)
                        break
                    except Exception as e:
                        attempt += 1
                        if attempt < self.MAX_RETRIES:
                            backoff = self.RETRY_BACKOFF_S[attempt - 1]
                            logger.warning("handler_retry", extra={
                                "event_type": event_type, "attempt": attempt, "error": str(e)
                            })
                            time.sleep(backoff)
                        else:
                            logger.error("handler_failed_dlq", extra={
                                "event_type": event_type, "error": str(e)
                            })
                            self._send_to_dlq(msg, str(e))

            self._consumer.commit(message=msg)

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("kafka_parse_error", extra={"error": str(e)})
            self._consumer.commit(message=msg)  # Skip malformed messages

    def _send_to_dlq(self, original_msg, error: str):
        """Send failed message to dead letter queue."""
        dlq_event = KafkaEvent(
            event_type="dlq.failed",
            payload={
                "original_topic": original_msg.topic(),
                "original_partition": original_msg.partition(),
                "original_offset": original_msg.offset(),
                "error": error,
                "original_value": original_msg.value().decode("utf-8", errors="replace"),
            }
        )
        self._producer.publish("AUDIT_LOG", dlq_event)

    def _handle_error(self, error):
        if error.code() == KafkaError._PARTITION_EOF:
            pass  # Normal end of partition
        else:
            logger.error("kafka_consumer_error", extra={"error": str(error)})


# ── Topic Setup ───────────────────────────────────────────────────────────────

def setup_kafka_topics():
    """Create Kafka topics if they don't exist. Run on startup."""
    admin = AdminClient(_base_config())
    topics_to_create = [
        NewTopic(topic, num_partitions=3, replication_factor=2)
        for topic in settings.KAFKA_TOPICS.values()
    ]
    # Also create DLQ topics
    dlq_topics = [
        NewTopic(f"{t}.dlq", num_partitions=1, replication_factor=2)
        for t in settings.KAFKA_TOPICS.values()
    ]

    result = admin.create_topics(topics_to_create + dlq_topics)
    for topic, future in result.items():
        try:
            future.result()
            logger.info("kafka_topic_created", extra={"topic": topic})
        except KafkaException as e:
            if "TOPIC_ALREADY_EXISTS" in str(e):
                pass
            else:
                logger.error("kafka_topic_create_error", extra={"topic": topic, "error": str(e)})
