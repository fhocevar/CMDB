CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE assets (
    id SERIAL PRIMARY KEY,
    hostname VARCHAR(150) NOT NULL UNIQUE,
    asset_type VARCHAR(50) NOT NULL,
    environment VARCHAR(30) NOT NULL,
    criticality VARCHAR(20) NOT NULL,
    business_service VARCHAR(150) NOT NULL,
    ip_address VARCHAR(50),
    operating_system VARCHAR(100),
    cpu_cores INTEGER NOT NULL,
    memory_gb NUMERIC(12,2) NOT NULL,
    disk_gb NUMERIC(12,2) NOT NULL,
    network_mbps NUMERIC(12,2) NOT NULL,
    cluster_name VARCHAR(150),
    namespace VARCHAR(150),
    source VARCHAR(50) NOT NULL DEFAULT 'MANUAL',
    provider VARCHAR(50),
    external_id VARCHAR(255),
    labels_json TEXT,
    parent_asset_id INTEGER NULL REFERENCES assets(id),
    last_seen_at TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_assets_parent_asset_id ON assets(parent_asset_id);
CREATE INDEX idx_assets_asset_type ON assets(asset_type);
CREATE INDEX idx_assets_external_id ON assets(external_id);

CREATE TABLE metrics (
    id BIGSERIAL PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    metric_type VARCHAR(50) NOT NULL,
    metric_value NUMERIC(14,4) NOT NULL,
    metric_unit VARCHAR(30) NOT NULL,
    collected_at TIMESTAMP NOT NULL,
    source VARCHAR(50) NOT NULL
);

CREATE INDEX idx_metrics_asset_metric_collected
    ON metrics(asset_id, metric_type, collected_at DESC);

CREATE INDEX idx_metrics_metric_type_collected
    ON metrics(metric_type, collected_at DESC);

CREATE TABLE threshold_policies (
    id SERIAL PRIMARY KEY,
    asset_type VARCHAR(50) NOT NULL,
    metric_type VARCHAR(50) NOT NULL,
    warning_percent NUMERIC(10,2) NOT NULL,
    critical_percent NUMERIC(10,2) NOT NULL,
    saturation_percent NUMERIC(10,2) NOT NULL,
    trend_window_hours INTEGER NOT NULL DEFAULT 24,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE discovery_sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    source_type VARCHAR(50) NOT NULL,
    host VARCHAR(150),
    port INTEGER,
    environment VARCHAR(30),
    username VARCHAR(100),
    password VARCHAR(255),
    extra_config TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE discovery_jobs (
    id BIGSERIAL PRIMARY KEY,
    source_name VARCHAR(100) NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    status VARCHAR(30) NOT NULL,
    assets_found INTEGER NOT NULL DEFAULT 0,
    assets_updated INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE collector_agents (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES assets(id),
    agent_token VARCHAR(255) NOT NULL UNIQUE,
    agent_version VARCHAR(50) NOT NULL,
    hostname VARCHAR(150) NOT NULL,
    last_heartbeat TIMESTAMP,
    status VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
    operating_system VARCHAR(100),
    ip_address VARCHAR(50)
);

CREATE TABLE metric_baselines (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    metric_type VARCHAR(50) NOT NULL,
    baseline_avg NUMERIC(14,4) NOT NULL,
    baseline_peak NUMERIC(14,4) NOT NULL,
    reference_window_days INTEGER NOT NULL DEFAULT 7,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    action VARCHAR(100) NOT NULL,
    entity VARCHAR(100) NOT NULL,
    details TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
