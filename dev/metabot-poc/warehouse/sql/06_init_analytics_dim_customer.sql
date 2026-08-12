-- Customer dimensions for the analytics schema.
--
-- Two of them, at two different grains, because the data forces it.
--
-- dim_customer is (customer_id, pnl) — the grain the fact views key on. It
-- carries the demographics.
--
-- dim_global_customer is (global_customer_id) — one row per person, and the
-- only join target with a genuinely unique key. Metabase can only express
-- single-column foreign keys, so it is the sole declared join path; pointing an
-- FK at dim_customer.customer_id would fan every joined row out across both
-- PnLs and silently double revenue.
--
-- It deliberately carries no demographics. The two PnL profiles of the same
-- person disagree far too often to pick one: of 2,600 global customers, 1,400
-- differ on date of birth, 1,219 on province and 929 on gender. Only is_vip is
-- consistent, so only is_vip is promoted. Collapsing the rest would mean
-- inventing an answer to "what province is this person in", and a made-up
-- dimension value is worse than a missing one — the model cannot tell it is
-- wrong.

DROP VIEW IF EXISTS analytics.dim_customer;
DROP VIEW IF EXISTS analytics.dim_global_customer;

CREATE VIEW analytics.dim_customer AS
SELECT
    c.customer_id,
    c.pnl,
    c.global_customer_id,
    EXTRACT(YEAR FROM c.date_of_birth)::INT AS birth_year,
    c.gender,
    c.province,
    c.is_vip
FROM silver.customers c;

COMMENT ON VIEW analytics.dim_customer IS
    'One row per customer within a PnL unit (khách hàng). Join to fact_transactions or fact_events on BOTH customer_id and pnl. Use global_customer_id to reach fact_customer_features or to count a person once across GSM and VinFast.';

COMMENT ON COLUMN analytics.dim_customer.customer_id IS
    'Customer identifier within the PnL unit (mã khách hàng). Not unique on its own — always pair with pnl when joining.';
COMMENT ON COLUMN analytics.dim_customer.pnl IS
    'Profit-and-loss unit (đơn vị PnL): gsm or vinfast.';
COMMENT ON COLUMN analytics.dim_customer.global_customer_id IS
    'Cross-company customer identifier (mã khách hàng toàn hệ thống). The same person has one global_customer_id but a different customer_id in each PnL. Join key to analytics.fact_customer_features.';
COMMENT ON COLUMN analytics.dim_customer.birth_year IS
    'Year of birth (năm sinh). Derived from date of birth; the full date is not exposed.';
COMMENT ON COLUMN analytics.dim_customer.gender IS
    'Customer gender (giới tính).';
COMMENT ON COLUMN analytics.dim_customer.province IS
    'Customer home province (tỉnh thành của khách hàng). Distinct from the province on a transaction, which is where that transaction happened.';
COMMENT ON COLUMN analytics.dim_customer.is_vip IS
    'Whether the customer is flagged VIP (khách hàng VIP).';

-- -----------------------------------------------------------------------------
-- Global customer dimension — the conformed join target
-- -----------------------------------------------------------------------------
CREATE VIEW analytics.dim_global_customer AS
SELECT
    c.global_customer_id,
    BOOL_OR(c.is_vip) AS is_vip,
    BOOL_OR(c.pnl = 'gsm') AS has_gsm,
    BOOL_OR(c.pnl = 'vinfast') AS has_vinfast,
    COUNT(*)::INT AS pnl_count
FROM silver.customers c
GROUP BY c.global_customer_id;

COMMENT ON VIEW analytics.dim_global_customer IS
    'One row per person (khách hàng toàn hệ thống), unique on global_customer_id. The join target for fact_transactions, fact_events and fact_customer_features. Carries no demographics on purpose: a person''s GSM and VinFast profiles disagree on province, gender and date of birth, so those live in dim_customer at the PnL grain instead.';

COMMENT ON COLUMN analytics.dim_global_customer.global_customer_id IS
    'Cross-company customer identifier (mã khách hàng toàn hệ thống). Unique — count rows here for the number of distinct people.';
COMMENT ON COLUMN analytics.dim_global_customer.is_vip IS
    'Whether the person is flagged VIP (khách hàng VIP) in any PnL. The two profiles always agree on this field.';
COMMENT ON COLUMN analytics.dim_global_customer.has_gsm IS
    'Whether this person has a GSM customer profile (có dùng GSM).';
COMMENT ON COLUMN analytics.dim_global_customer.has_vinfast IS
    'Whether this person has a VinFast customer profile (có dùng VinFast). Combine with has_gsm to find customers who use both companies (khách hàng dùng cả hai).';
COMMENT ON COLUMN analytics.dim_global_customer.pnl_count IS
    'How many PnL units this person appears in (1 or 2).';
