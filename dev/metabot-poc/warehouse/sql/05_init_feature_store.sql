-- Governed, versioned Feature Store registry and monthly serving values.
--
-- Taken from scripts/sql/05_init_feature_store.sql in the previous BI project,
-- unchanged apart from this header. The constraints are the point of the table:
-- registry rows are immutable by convention, only engineering-reviewed features
-- may land, and every row carries the provenance hash of the artifact it came
-- from. Keeping them here means the POC loads the same governed shape rather
-- than a flattened copy that has quietly dropped the guarantees.
--
-- Nothing in this schema is exposed to Metabase. The BI connection only sees
-- `analytics`, which gets a pivoted, commented view built in 07. See that file
-- for why the serving table is not queried directly.

CREATE SCHEMA IF NOT EXISTS feature_store;

CREATE TABLE IF NOT EXISTS feature_store.feature_registry (
    registry_version VARCHAR(32) NOT NULL,
    feature_name VARCHAR(255) NOT NULL,
    domain VARCHAR(100) NOT NULL,
    entity VARCHAR(100) NOT NULL,
    grain VARCHAR(100) NOT NULL,
    window_name VARCHAR(50) NOT NULL,
    source_artifact TEXT NOT NULL,
    source_column VARCHAR(255) NOT NULL,
    owner_name VARCHAR(100) NOT NULL,
    semantic_status VARCHAR(50) NOT NULL,
    business_approval_status VARCHAR(50) NOT NULL,
    source_metadata_status VARCHAR(50) NOT NULL,
    definition_source VARCHAR(100) NOT NULL,
    value_type VARCHAR(20) NOT NULL,
    nullable BOOLEAN NOT NULL,
    governance_decision_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    assumption_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    dq_checks JSONB NOT NULL,
    review_group_id VARCHAR(100) NOT NULL,
    review_decision_hash CHAR(64) NOT NULL,
    provenance_hash CHAR(64) NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (registry_version, feature_name),
    CONSTRAINT ck_feature_registry_version
        CHECK (registry_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    CONSTRAINT ck_feature_registry_semantic_status
        CHECK (semantic_status = 'engineering_reviewed'),
    CONSTRAINT ck_feature_registry_no_finished
        CHECK (LOWER(feature_name) NOT LIKE '%finished%'),
    CONSTRAINT ck_feature_registry_hash
        CHECK (provenance_hash ~ '^[a-f0-9]{64}$')
);

CREATE TABLE IF NOT EXISTS feature_store.feature_values_monthly (
    registry_version VARCHAR(32) NOT NULL,
    source_snapshot_hash CHAR(64) NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    global_customer_id VARCHAR(50) NOT NULL,
    snapshot_month VARCHAR(7) NOT NULL,
    feature_name VARCHAR(255) NOT NULL,
    feature_value TEXT,
    value_type VARCHAR(20) NOT NULL,
    feature_provenance_hash CHAR(64) NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (
        registry_version,
        source_snapshot_hash,
        customer_id,
        pnl,
        snapshot_month,
        feature_name
    ),
    CONSTRAINT fk_feature_values_registry
        FOREIGN KEY (registry_version, feature_name)
        REFERENCES feature_store.feature_registry (registry_version, feature_name),
    CONSTRAINT ck_feature_values_source_hash
        CHECK (source_snapshot_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT ck_feature_values_provenance_hash
        CHECK (feature_provenance_hash ~ '^[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_feature_values_entity_month
    ON feature_store.feature_values_monthly (
        global_customer_id,
        snapshot_month,
        feature_name
    );

CREATE INDEX IF NOT EXISTS idx_feature_values_lookup
    ON feature_store.feature_values_monthly (
        registry_version,
        feature_name,
        pnl,
        snapshot_month
    );

COMMENT ON SCHEMA feature_store IS
    'Engineering-reviewed Feature Store. Business approval remains explicit in the registry.';

COMMENT ON TABLE feature_store.feature_values_monthly IS
    'Content-addressed serving snapshots; a new source hash appends history instead of overwriting it.';
