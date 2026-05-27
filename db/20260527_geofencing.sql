-- Migration: 20260527_geofencing
-- Description: Create geofences and webhooks tables for the MQTT/Geofencing feature.
-- Feature: FEAT-005 — MQTT + RabbitMQ Broker with Geofencing
-- Author: sdd-worker
-- Date: 2026-05-27
--
-- This migration is idempotent (uses IF NOT EXISTS) and may be run multiple times.
-- Polygons are stored as TEXT (GeoJSON or WKT) — no PostGIS extension required.
-- Secret storage in webhooks.secret_encrypted uses BYTEA for the encrypted key.

-- -------------------------------------------------------------------------
-- geofences
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geofences (
    id              SERIAL PRIMARY KEY,
    tenant_id       VARCHAR(64) NOT NULL,
    name            VARCHAR(128) NOT NULL,
    polygon         TEXT NOT NULL,           -- GeoJSON or WKT; evaluated in-memory by Shapely
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    dwell_seconds   INTEGER NULL,             -- per-geofence dwell override; NULL = use GEOFENCE_DWELL_DURATION
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_geofences_tenant_active
    ON geofences (tenant_id, active);

-- -------------------------------------------------------------------------
-- webhooks
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS webhooks (
    id                SERIAL PRIMARY KEY,
    tenant_id         VARCHAR(64) NOT NULL,
    url               TEXT NOT NULL,
    secret_encrypted  BYTEA NOT NULL,          -- HMAC secret, encrypted at rest
    geofence_filter   INTEGER NULL REFERENCES geofences(id) ON DELETE SET NULL,
    active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhooks_tenant_active
    ON webhooks (tenant_id, active);
