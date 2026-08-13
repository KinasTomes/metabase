-- Curated, read-only BI views for the MetaBot POC.
--
-- Replaces the monthly-aggregate views used by the previous BI project. Those
-- were pre-aggregated to month x company, which drops the product, province,
-- and event-name dimensions the demo question set asks about. MetaBot writes
-- its own GROUP BY, so it needs fact-grain views instead.
--
-- Column comments are the main lever we have on answer quality: this POC has no
-- :ai-controls entitlement, so the system prompt cannot be customized. Metabase
-- syncs these comments into field descriptions, which do reach the model, so
-- each one carries the Vietnamese business term alongside the English name.

CREATE SCHEMA IF NOT EXISTS analytics;

-- The analytics schema is the only warehouse surface exposed to Metabase.
-- Access for the dedicated login is granted after the views exist. Keeping
-- PUBLIC out prevents an accidental broad grant from turning the BI connection
-- into a Bronze/Silver browser.
REVOKE ALL ON SCHEMA analytics FROM PUBLIC;

DROP VIEW IF EXISTS analytics.fact_transactions;
DROP VIEW IF EXISTS analytics.fact_events;

-- -----------------------------------------------------------------------------
-- Transactions
-- -----------------------------------------------------------------------------
-- transaction_date is TIMESTAMPTZ at midnight UTC. A bare ::DATE would resolve
-- against the session time zone, so any connection west of UTC would shift
-- every row back a day. Metabase sets the session zone from its report-timezone
-- setting, so pin the conversion to UTC. transaction_month needs no such
-- treatment: it arrives from Silver as a literal YYYY-MM string.
CREATE VIEW analytics.fact_transactions AS
SELECT
    t.transaction_id,
    (t.transaction_date AT TIME ZONE 'UTC')::DATE AS transaction_date,
    t.transaction_month,
    t.company,
    t.pnl,
    t.product,
    t.province,
    t.status,
    t.amount AS revenue,
    t.customer_id,
    t.global_customer_id
FROM silver.transactions t;

COMMENT ON VIEW analytics.fact_transactions IS
    'One row per transaction (giao dịch). Revenue and transaction counts for GSM and VinFast, broken down by month, product, and province. Carries completed transactions only — see the status column before answering anything about cancellations.';

COMMENT ON COLUMN analytics.fact_transactions.transaction_id IS
    'Unique transaction identifier. Count rows to get số giao dịch (transaction count).';
COMMENT ON COLUMN analytics.fact_transactions.transaction_date IS
    'Date the transaction occurred (ngày giao dịch). Data covers 2025-01-01 to 2025-12-28 only.';
COMMENT ON COLUMN analytics.fact_transactions.transaction_month IS
    'Calendar month of the transaction as YYYY-MM (tháng). Use for monthly trends.';
COMMENT ON COLUMN analytics.fact_transactions.company IS
    'Operating company (công ty): GSM or VinFast.';
COMMENT ON COLUMN analytics.fact_transactions.pnl IS
    'Profit-and-loss unit (đơn vị PnL): gsm or vinfast. Lowercase counterpart of company.';
COMMENT ON COLUMN analytics.fact_transactions.product IS
    'Product or service line (sản phẩm). GSM sells taxi, bike, food, express; VinFast sells vehicle, accessories, service.';
COMMENT ON COLUMN analytics.fact_transactions.province IS
    'Vietnamese province where the transaction took place (tỉnh, tỉnh thành).';
COMMENT ON COLUMN analytics.fact_transactions.status IS
    'Transaction status (trạng thái). Every row here is ''completed'', because the data contract materialises only completed transactions into this fact layer. This does NOT mean cancellations do not happen: ''cancelled'' (giao dịch bị huỷ) is an approved business status, reported separately, but no cancelled fact has been loaded or reconciled yet. For a cancelled question, say the fact layer currently carries completed only and that no verified cancelled figure is available — do not answer 0, and do not take a number from any other source. See analytics.dim_feature_catalogue.';
COMMENT ON COLUMN analytics.fact_transactions.revenue IS
    'Transaction amount in VND (doanh thu, giá trị giao dịch). Sum for total revenue. Note: VinFast rows are all 0, so VinFast revenue is not meaningful — use transaction counts for VinFast instead.';
COMMENT ON COLUMN analytics.fact_transactions.customer_id IS
    'Customer identifier within the PnL unit (mã khách hàng). Not unique across companies — pair with pnl.';
COMMENT ON COLUMN analytics.fact_transactions.global_customer_id IS
    'Cross-company customer identifier (mã khách hàng toàn hệ thống). Count distinct for unique customers across GSM and VinFast.';

-- -----------------------------------------------------------------------------
-- Events
-- -----------------------------------------------------------------------------
-- Same UTC pinning as fact_transactions, and here it also covers event_month:
-- Silver carries no month column for events, so it is derived. Verified: under
-- America/Los_Angeles the unpinned version produced 13 month buckets and leaked
-- 59 events into 2024-12.
CREATE VIEW analytics.fact_events AS
SELECT
    e.event_id,
    (e.event_date AT TIME ZONE 'UTC')::DATE AS event_date,
    TO_CHAR(e.event_date AT TIME ZONE 'UTC', 'YYYY-MM') AS event_month,
    e.company,
    e.pnl,
    e.event_name,
    e.province,
    e.customer_id,
    e.global_customer_id
FROM silver.events e;

COMMENT ON VIEW analytics.fact_events IS
    'One row per app event (sự kiện) for GSM and VinFast. Use for engagement questions: event counts by month, event name, or province. Contains no revenue.';

COMMENT ON COLUMN analytics.fact_events.event_id IS
    'Unique event identifier. Count rows to get số event (event count).';
COMMENT ON COLUMN analytics.fact_events.event_date IS
    'Date the event occurred (ngày sự kiện). Data covers 2025-01-01 to 2025-12-28 only.';
COMMENT ON COLUMN analytics.fact_events.event_month IS
    'Calendar month of the event as YYYY-MM (tháng). Use for monthly trends.';
COMMENT ON COLUMN analytics.fact_events.company IS
    'Operating company (công ty): GSM or VinFast.';
COMMENT ON COLUMN analytics.fact_events.pnl IS
    'Profit-and-loss unit (đơn vị PnL): gsm or vinfast. Lowercase counterpart of company.';
COMMENT ON COLUMN analytics.fact_events.event_name IS
    'Type of user action (tên sự kiện): app_open, search, view_product, booking_created, booking_completed, support_contact.';
COMMENT ON COLUMN analytics.fact_events.province IS
    'Vietnamese province where the event took place (tỉnh, tỉnh thành).';
COMMENT ON COLUMN analytics.fact_events.customer_id IS
    'Customer identifier within the PnL unit (mã khách hàng). Not unique across companies — pair with pnl.';
COMMENT ON COLUMN analytics.fact_events.global_customer_id IS
    'Cross-company customer identifier (mã khách hàng toàn hệ thống).';

REVOKE ALL ON ALL TABLES IN SCHEMA analytics FROM PUBLIC;
