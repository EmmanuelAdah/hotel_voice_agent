-- ════════════════════════════════════════════════════════════════════════════
-- Hotel Voice Agent — Database Initialization & Optimization Script
-- ════════════════════════════════════════════════════════════════════════════

-- Extensions
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- trigram indexes for search
CREATE EXTENSION IF NOT EXISTS btree_gin;   -- GIN indexes for composite queries
CREATE EXTENSION IF NOT EXISTS uuid-ossp;   -- UUID generation

-- ── PostgreSQL Performance Tuning (applied via postgresql.conf or ALTER SYSTEM)
-- These match the docker-compose pg command flags:
--   shared_buffers=256MB
--   effective_cache_size=768MB
--   maintenance_work_mem=64MB
--   checkpoint_completion_target=0.9
--   wal_buffers=16MB
--   default_statistics_target=100
--   random_page_cost=1.1
--   effective_io_concurrency=200
--   work_mem=4MB

-- ── Partial Indexes (only index what matters) ─────────────────────────────────

-- Active users only (most queries filter by is_active=true)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_active_email
    ON core_users (email) WHERE is_active = TRUE;

-- Available rooms (most frequent query)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_room_available
    ON core_rooms (room_type, price_per_night)
    WHERE status = 'available' AND is_active = TRUE;

-- Open service requests (most frequent staff query)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sr_open
    ON core_service_requests (priority DESC, created_at DESC)
    WHERE status IN ('pending', 'assigned', 'in_progress');

-- Pending service requests by type
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sr_pending_type
    ON core_service_requests (service_type, created_at DESC)
    WHERE status = 'pending';

-- Active voice sessions
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vs_active
    ON core_voice_sessions (guest_id, started_at DESC)
    WHERE status = 'active';

-- Upcoming bookings
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_booking_upcoming
    ON core_bookings (check_in, room_id)
    WHERE status IN ('confirmed', 'checked_in');

-- ── Covering Indexes (index-only scans) ──────────────────────────────────────

-- Guest booking list (no heap access needed for common query)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_booking_guest_cover
    ON core_bookings (guest_id, status, check_in, check_out)
    INCLUDE (confirmation_code, room_id, total_price);

-- Service request list for staff dashboard
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sr_dashboard_cover
    ON core_service_requests (status, priority, service_type, created_at)
    INCLUDE (guest_id, booking_id, assigned_to_id, description);

-- ── Trigram Indexes for Text Search ──────────────────────────────────────────
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_email_trgm
    ON core_users USING GIN (email gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_room_desc_trgm
    ON core_rooms USING GIN (description gin_trgm_ops);

-- ── BRIN Indexes for time-series (append-only tables) ────────────────────────
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_brin
    ON core_audit_logs USING BRIN (timestamp) WITH (pages_per_range = 128);

-- ── Optimized Queries (as views for common operations) ──────────────────────

-- Dashboard: pending service requests with room info
CREATE OR REPLACE VIEW v_pending_service_requests AS
SELECT
    sr.id,
    sr.service_type,
    sr.priority,
    sr.description,
    sr.created_at,
    u.email AS guest_email,
    u.first_name || ' ' || u.last_name AS guest_name,
    r.number AS room_number,
    r.floor AS room_floor
FROM core_service_requests sr
JOIN core_users u ON sr.guest_id = u.id
JOIN core_bookings b ON sr.booking_id = b.id
JOIN core_rooms r ON b.room_id = r.id
WHERE sr.status IN ('pending', 'assigned')
ORDER BY
    CASE sr.priority
        WHEN 'urgent' THEN 1
        WHEN 'high' THEN 2
        WHEN 'normal' THEN 3
        WHEN 'low' THEN 4
    END,
    sr.created_at DESC;

-- Analytics: daily voice session stats
CREATE OR REPLACE VIEW v_voice_session_stats_daily AS
SELECT
    date_trunc('day', started_at) AS day,
    COUNT(*) AS total_sessions,
    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
    AVG(duration_seconds) FILTER (WHERE status = 'completed') AS avg_duration_s,
    SUM(tokens_used) AS total_tokens,
    SUM(tts_characters) AS total_tts_chars
FROM core_voice_sessions
GROUP BY date_trunc('day', started_at)
ORDER BY day DESC;

-- ── Table Statistics Tuning ──────────────────────────────────────────────────
ALTER TABLE core_service_requests ALTER COLUMN status SET STATISTICS 500;
ALTER TABLE core_service_requests ALTER COLUMN service_type SET STATISTICS 500;
ALTER TABLE core_bookings ALTER COLUMN status SET STATISTICS 500;
ALTER TABLE core_voice_sessions ALTER COLUMN status SET STATISTICS 500;

-- Run ANALYZE after creating indexes
ANALYZE core_users;
ANALYZE core_rooms;
ANALYZE core_bookings;
ANALYZE core_service_requests;
ANALYZE core_voice_sessions;
ANALYZE core_audit_logs;
