-- =============================================================================
-- DDL Script: Bronze, Silver, and Gold Schemas for BI Agent
-- Contract Version: 0.3-mvp
-- =============================================================================

-- Enable pgvector extension if available
CREATE EXTENSION IF NOT EXISTS vector;

-- -----------------------------------------------------------------------------
-- 1. BRONZE SCHEMA (Raw Ingestion)
-- -----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.dim_global_customer (
    customer_id VARCHAR(50) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    global_customer_id VARCHAR(50) NOT NULL,
    ingested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    source_file VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS bronze.customers (
    customer_id VARCHAR(50) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    date_of_birth DATE,
    gender VARCHAR(20),
    province VARCHAR(100),
    is_vip VARCHAR(10),
    ingested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    source_file VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS bronze.transactions (
    transaction_id VARCHAR(50) NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    company VARCHAR(50),
    transaction_date TIMESTAMPTZ,
    product VARCHAR(100),
    status VARCHAR(50),
    amount NUMERIC(15, 2),
    province VARCHAR(100),
    from_location VARCHAR(255),
    to_location VARCHAR(255),
    from_lat NUMERIC(10, 6),
    from_long NUMERIC(10, 6),
    to_lat NUMERIC(10, 6),
    to_long NUMERIC(10, 6),
    ingested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    source_file VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS bronze.events (
    event_id VARCHAR(50) NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    company VARCHAR(50),
    event_date TIMESTAMPTZ,
    event_name VARCHAR(100),
    province VARCHAR(100),
    from_location VARCHAR(255),
    to_location VARCHAR(255),
    from_lat NUMERIC(10, 6),
    from_long NUMERIC(10, 6),
    to_lat NUMERIC(10, 6),
    to_long NUMERIC(10, 6),
    ingested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    source_file VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS bronze.loyalty_transactions (
    loyalty_txn_id VARCHAR(50) NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    company VARCHAR(50),
    loyalty_date TIMESTAMPTZ,
    transaction_type VARCHAR(50),
    points INT,
    status VARCHAR(50),
    ingested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    source_file VARCHAR(255)
);

-- -----------------------------------------------------------------------------
-- 2. SILVER SCHEMA (Cleansed, Typed, Keyed)
-- -----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE IF NOT EXISTS silver.dim_global_customer (
    customer_id VARCHAR(50) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    global_customer_id VARCHAR(50) NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (customer_id, pnl)
);

CREATE TABLE IF NOT EXISTS silver.customers (
    customer_id VARCHAR(50) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    global_customer_id VARCHAR(50) NOT NULL,
    date_of_birth DATE,
    gender VARCHAR(20),
    province VARCHAR(100),
    is_vip BOOLEAN,
    processed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (customer_id, pnl),
    CONSTRAINT fk_customers_dim_global FOREIGN KEY (customer_id, pnl) REFERENCES silver.dim_global_customer (customer_id, pnl)
);

CREATE TABLE IF NOT EXISTS silver.transactions (
    transaction_id VARCHAR(50) PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    global_customer_id VARCHAR(50) NOT NULL,
    company VARCHAR(50) NOT NULL,
    transaction_date TIMESTAMPTZ NOT NULL,
    transaction_month VARCHAR(7) NOT NULL,
    product VARCHAR(100),
    status VARCHAR(50) NOT NULL,
    amount NUMERIC(15, 2) NOT NULL,
    province VARCHAR(100),
    from_location VARCHAR(255),
    to_location VARCHAR(255),
    from_lat NUMERIC(10, 6),
    from_long NUMERIC(10, 6),
    to_lat NUMERIC(10, 6),
    to_long NUMERIC(10, 6),
    processed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_transactions_customer FOREIGN KEY (customer_id, pnl) REFERENCES silver.customers (customer_id, pnl)
);

CREATE TABLE IF NOT EXISTS silver.events (
    event_id VARCHAR(50) PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    global_customer_id VARCHAR(50) NOT NULL,
    company VARCHAR(50) NOT NULL,
    event_date TIMESTAMPTZ NOT NULL,
    event_name VARCHAR(100) NOT NULL,
    province VARCHAR(100),
    from_location VARCHAR(255),
    to_location VARCHAR(255),
    from_lat NUMERIC(10, 6),
    from_long NUMERIC(10, 6),
    to_lat NUMERIC(10, 6),
    to_long NUMERIC(10, 6),
    processed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_events_customer FOREIGN KEY (customer_id, pnl) REFERENCES silver.customers (customer_id, pnl)
);

CREATE TABLE IF NOT EXISTS silver.loyalty_transactions (
    loyalty_txn_id VARCHAR(50) PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    global_customer_id VARCHAR(50) NOT NULL,
    company VARCHAR(50) NOT NULL,
    loyalty_date TIMESTAMPTZ NOT NULL,
    transaction_type VARCHAR(50) NOT NULL,
    points INT NOT NULL,
    status VARCHAR(50) NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_loyalty_customer FOREIGN KEY (customer_id, pnl) REFERENCES silver.customers (customer_id, pnl)
);

-- -----------------------------------------------------------------------------
-- 3. GOLD SCHEMA (Aggregated Facts & Dimensions)
-- -----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.gold_monthly_pnl (
    month VARCHAR(7) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    company VARCHAR(50) NOT NULL,
    revenue NUMERIC(15, 2) NOT NULL,
    transaction_count INT NOT NULL,
    customer_count INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (month, pnl, company)
);

CREATE TABLE IF NOT EXISTS gold.gold_monthly_global (
    month VARCHAR(7) PRIMARY KEY,
    revenue NUMERIC(15, 2) NOT NULL,
    transaction_count INT NOT NULL,
    global_customer_count INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gold.gold_customer_monthly (
    month VARCHAR(7) NOT NULL,
    pnl VARCHAR(20) NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    global_customer_id VARCHAR(50) NOT NULL,
    revenue NUMERIC(15, 2) NOT NULL,
    transaction_count INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (month, pnl, customer_id)
);
