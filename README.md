# 🏨 Hotel Voice Agent

A **production-ready AI Voice Agent** for hotel services, built with Django, OpenAI, Kafka, and a full observability stack.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          NGINX (Load Balancer)                       │
│         Rate Limiting · TLS Termination · WebSocket Proxy            │
└───────────────┬─────────────────────────┬────────────────────────────┘
                │ HTTP                    │ WebSocket (ws://)
         ┌──────▼───────┐         ┌───────▼──────────┐
         │  Gunicorn    │         │   Daphne (ASGI)  │
         │  (2 workers) │         │  (2 workers)     │
         └──────┬───────┘         └───────┬──────────┘
                │                         │
         ┌──────▼─────────────────────────▼──────┐
         │              Django Application              │
         │  ┌─────────────┐   ┌──────────────────┐    │
         │  │ REST API v1  │   │ Channels (WS)    │    │
         │  │ JWT Auth     │   │ Voice Sessions   │    │
         │  └──────┬───────┘   └────────┬─────────┘    │
         │         │                    │              │
         │  ┌──────▼────────────────────▼──────────┐  │
         │  │          Voice Agent Service          │  │
         │  │  Whisper STT → GPT-4o → TTS-1-HD    │  │
         │  └───────────────────────────────────────┘  │
         └──────┬────────────┬───────────────┬──────────┘
                │            │               │
         ┌──────▼──┐  ┌──────▼──┐    ┌──────▼──┐
         │PostgreSQL│  │  Redis  │    │  Kafka  │
         │(Primary/ │  │(Cache/  │    │(3 topics│
         │ Replica) │  │Sessions)│    │ + DLQ)  │
         └─────────┘  └─────────┘    └──────┬──┘
                                            │
                                    ┌───────▼──────┐
                                    │Kafka Consumer│
                                    │(2 workers)   │
                                    └──────────────┘

         ┌─────────────────────────────────────────────┐
         │              Observability                  │
         │  Prometheus → Grafana Dashboards + Alerts   │
         │  Sentry · Structured JSON Logging           │
         └─────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer              | Technology                                          |
|--------------------|-----------------------------------------------------|
| **Framework**      | Django 5, Django REST Framework                    |
| **AI / Voice**     | OpenAI GPT-4o, Whisper STT, TTS-1-HD               |
| **Real-time**      | Django Channels, Daphne, WebSocket                 |
| **Async Tasks**    | Celery + Redis                                      |
| **Event Bus**      | Apache Kafka (confluent-kafka)                      |
| **Database**       | PostgreSQL 16 + Read Replica, optimized indexes    |
| **Cache**          | Redis 7 (sessions, rate limiting, query cache)     |
| **Auth**           | JWT (SimpleJWT) + Argon2 password hashing          |
| **Load Balancer**  | Nginx (upstream round-robin + WebSocket sticky)    |
| **Rate Limiting**  | Nginx zones + DRF throttles + custom middleware    |
| **Metrics**        | Prometheus + Grafana (pre-built dashboards)        |
| **Error Tracking** | Sentry                                              |
| **Containers**     | Docker + Docker Compose                             |
| **Package Mgr**    | `uv` (fast, lockfile-based)                        |

---

## Quick Start

### Prerequisites
- Docker + Docker Compose v2
- `uv` (`pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- OpenAI API key

### 1 — Clone & configure
```bash
git clone https://github.com/your-org/hotel-voice-agent.git
cd hotel-voice-agent
cp .env.example .env
# Edit .env — set DJANGO_SECRET_KEY, DB_PASSWORD, OPENAI_API_KEY at minimum
```

### 2 — Start with Docker Compose
```bash
docker compose up -d
```
First start takes ~2 minutes. Run migrations and seed demo data:
```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_demo_data
```

### 3 — Access services
| Service     | URL                          | Credentials             |
|-------------|------------------------------|-------------------------|
| API         | http://localhost/api/v1/     | See below               |
| Grafana     | http://localhost:3000        | admin / $GRAFANA_PASSWORD |
| Prometheus  | http://localhost:9090        | —                       |
| Django Admin| http://localhost/admin/      | admin@demo.com / Demo1234! |

### Demo credentials (after seed)
```
Guest:   guest@demo.com   / Demo1234!
Staff:   staff@demo.com   / Demo1234!
Manager: manager@demo.com / Demo1234!
Admin:   admin@demo.com   / Demo1234!
```

---

## Local Development

```bash
# Install dependencies
uv sync

# Set env vars
export DJANGO_SETTINGS_MODULE=hotel_agent.settings.development
export DJANGO_SECRET_KEY=dev-secret
export DB_PASSWORD=postgres
export OPENAI_API_KEY=sk-...

# Run Django dev server
uv run manage.py runserver

# Run Celery worker
uv run celery -A hotel_agent worker --loglevel=debug

# Run Kafka consumer
uv run manage.py run_kafka_consumer
```

### Run tests
```bash
uv run pytest                          # all tests
uv run pytest tests/unit/              # unit only
uv run pytest -k "voice" -v           # filter by name
uv run pytest --cov-report=html       # HTML coverage report
```

---

## API Reference

### Authentication
```bash
# Register
POST /api/v1/auth/register/
{"email": "guest@hotel.com", "password": "...", "confirm_password": "...", "first_name": "...", "last_name": "..."}

# Login → JWT tokens
POST /api/v1/auth/token/
{"email": "...", "password": "..."}

# Refresh token
POST /api/v1/auth/token/refresh/
{"refresh": "<refresh_token>"}

# Logout (blacklist refresh token)
POST /api/v1/auth/token/blacklist/
{"refresh": "<refresh_token>"}
```

### Voice Sessions
```bash
# Start session
POST /api/v1/voice/sessions/
Authorization: Bearer <token>
{"booking_id": "<uuid>"}

# Process a turn (text input)
POST /api/v1/voice/sessions/<id>/turn/
{"text": "I'd like room service please", "generate_audio": true}
# Returns: {"text": "...", "audio_base64": "...", "service_request_created": {...}?}

# Process a turn (audio upload)
POST /api/v1/voice/sessions/<id>/turn/
Content-Type: multipart/form-data
audio=<webm file>

# End session
POST /api/v1/voice/sessions/<id>/end/

# Get transcript
GET /api/v1/voice/sessions/<id>/transcript/
```

### WebSocket (real-time voice)
```
ws://localhost/ws/voice/<session_id>/?token=<jwt_access_token>

# Send text turn:
{"type": "voice_input", "text": "I need extra towels", "generate_audio": true}

# Send audio turn:
{"type": "audio_input", "audio_b64": "<base64 webm>", "format": "webm"}

# Receive:
{"type": "response_text", "text": "..."}
{"type": "response_audio", "audio_b64": "...", "format": "mp3"}
{"type": "service_request_detected", "data": {"service_type": "housekeeping", ...}}
{"type": "notification", "message": "...", "data": {...}}
```

### Service Requests
```bash
GET  /api/v1/service-requests/           # list
POST /api/v1/service-requests/           # create manually
POST /api/v1/service-requests/<id>/assign/   # staff self-assign
POST /api/v1/service-requests/<id>/complete/ # mark done

# Filters: ?status=pending&service_type=room_service&priority=high
```

### Rooms & Bookings
```bash
GET /api/v1/rooms/                       # list available rooms
GET /api/v1/rooms/?room_type=suite       # filter by type

POST /api/v1/bookings/                   # create booking
GET  /api/v1/bookings/<id>/             # booking detail
```

---

## Kafka Topics

| Topic                    | Events                              |
|--------------------------|-------------------------------------|
| `hotel.voice.sessions`   | session started/completed           |
| `hotel.service.requests` | request created/assigned/completed  |
| `hotel.notifications`    | push notifications to guests/staff  |
| `hotel.analytics`        | usage metrics                       |
| `hotel.audit.log`        | all audit events                    |
| `*.dlq`                  | Dead letter queue per topic         |

---

## Database Indexes

Key optimized indexes defined in `scripts/init_db.sql`:

- **Partial indexes** — available rooms, open service requests, active sessions
- **Covering indexes** — guest booking list, staff dashboard (index-only scans)
- **BRIN indexes** — audit log timestamps (append-only table)
- **Trigram indexes** — email and description full-text search
- **Composite indexes** — all common filter combinations

---

## Security Features

- **JWT** with 30-min access + 7-day refresh tokens, rotation + blacklist
- **Argon2** password hashing
- **Account lockout** — 5 failed attempts → 30-min lock
- **Rate limiting** — Nginx zones + DRF throttles + custom Redis middleware
- **HTTPS enforced** — HSTS + strict TLS config
- **Security headers** — CSP, X-Frame-Options, nosniff, XSS protection
- **Admin restricted** — IP allowlist via Nginx
- **Metrics endpoint** — Docker network only (not publicly exposed)

---

## Production Deployment

```bash
./scripts/deploy.sh
```

The script:
1. Validates required env vars
2. Pulls infrastructure images
3. Builds the Django image (multi-stage, non-root user)
4. Starts Postgres, Redis, Kafka
5. Runs database migrations
6. Sets up Kafka topics
7. Deploys all app services (2 replicas each)
8. Runs a health check

---

## Monitoring

### Grafana Dashboard
Pre-provisioned dashboard at **http://localhost:3000** showing:
- Active voice sessions & sessions/min
- Voice turn latency (p50/p95/p99)
- OpenAI token usage
- Service request breakdown by type
- Kafka consumer lag
- API error rates
- Database query latency
- Redis memory usage

### Prometheus Alerts
Pre-configured alerts for:
- High API error rate (>5%)
- Slow voice turns (p95 >5s)
- OpenAI API errors
- Kafka consumer lag >1000
- DB connections near limit
- Redis memory >85%
- Messages going to DLQ
