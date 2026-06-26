"""
Prometheus metrics for Hotel Voice Agent.
All metrics are defined centrally and imported by views/services.
"""
from prometheus_client import Counter, Histogram, Gauge, Summary, Info

# ── Voice Agent Metrics ───────────────────────────────────────────────────────

VOICE_SESSION_COUNTER = Counter(
    "hotel_voice_sessions_total",
    "Total voice sessions initiated",
    ["status", "room_type"],
)

VOICE_SESSION_DURATION = Histogram(
    "hotel_voice_session_duration_seconds",
    "Voice session duration in seconds",
    buckets=[10, 30, 60, 120, 300, 600],
)

VOICE_TURN_LATENCY = Histogram(
    "hotel_voice_turn_latency_seconds",
    "Latency for a single voice turn (STT + LLM + TTS)",
    buckets=[0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
)

LLM_TOKENS_USED = Counter(
    "hotel_llm_tokens_total",
    "Total OpenAI tokens consumed",
    ["model", "direction"],  # direction: input | output
)

TTS_CHARACTERS_SYNTHESIZED = Counter(
    "hotel_tts_characters_total",
    "Total characters synthesized via TTS",
)

OPENAI_API_ERRORS = Counter(
    "hotel_openai_errors_total",
    "Total OpenAI API errors",
    ["error_type", "service"],  # service: whisper | chat | tts
)

ACTIVE_VOICE_SESSIONS = Gauge(
    "hotel_active_voice_sessions",
    "Currently active voice sessions",
)

# ── Service Request Metrics ───────────────────────────────────────────────────

SERVICE_REQUEST_COUNTER = Counter(
    "hotel_service_requests_total",
    "Total service requests created",
    ["service_type", "priority", "source"],  # source: voice | api | manual
)

SERVICE_REQUEST_COMPLETION_TIME = Histogram(
    "hotel_service_request_completion_seconds",
    "Time from creation to completion for service requests",
    ["service_type", "priority"],
    buckets=[60, 300, 600, 1800, 3600, 7200],
)

SERVICE_REQUEST_STATUS = Gauge(
    "hotel_service_requests_by_status",
    "Current service requests by status",
    ["status"],
)

# ── Kafka Metrics ─────────────────────────────────────────────────────────────

KAFKA_MESSAGES_PRODUCED = Counter(
    "hotel_kafka_messages_produced_total",
    "Total Kafka messages produced",
    ["topic"],
)

KAFKA_MESSAGES_CONSUMED = Counter(
    "hotel_kafka_messages_consumed_total",
    "Total Kafka messages consumed",
    ["topic", "event_type"],
)

KAFKA_CONSUMER_LAG = Gauge(
    "hotel_kafka_consumer_lag",
    "Kafka consumer lag per topic-partition",
    ["topic", "partition"],
)

KAFKA_DLQ_MESSAGES = Counter(
    "hotel_kafka_dlq_messages_total",
    "Messages sent to dead letter queue",
    ["original_topic"],
)

KAFKA_PROCESSING_LATENCY = Histogram(
    "hotel_kafka_processing_latency_seconds",
    "Time to process a Kafka message",
    ["event_type"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

# ── API Metrics ───────────────────────────────────────────────────────────────

API_REQUEST_LATENCY = Histogram(
    "hotel_api_request_duration_seconds",
    "API request duration",
    ["method", "endpoint", "status_code"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

API_RATE_LIMIT_HITS = Counter(
    "hotel_rate_limit_hits_total",
    "Total rate limit violations",
    ["endpoint"],
)

AUTH_ATTEMPTS = Counter(
    "hotel_auth_attempts_total",
    "Authentication attempts",
    ["result"],  # success | failure | locked
)

# ── Database Metrics ──────────────────────────────────────────────────────────

DB_QUERY_DURATION = Histogram(
    "hotel_db_query_duration_seconds",
    "Database query duration",
    ["operation", "model"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)

DB_CONNECTION_POOL = Gauge(
    "hotel_db_connection_pool_size",
    "Database connection pool utilization",
    ["db_alias"],
)

# ── System Info ───────────────────────────────────────────────────────────────

APP_INFO = Info(
    "hotel_voice_agent",
    "Hotel Voice Agent application info",
)
APP_INFO.info({"version": "1.0.0", "environment": "production"})
