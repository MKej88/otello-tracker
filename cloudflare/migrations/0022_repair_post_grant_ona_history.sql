-- Reparer historiske ONA-rader mellom de to første rapportankrene som begge
-- ligger etter opsjonsgrantet 15.09.2025.
--
-- Den gamle interpoleringen brukte ONA inklusive rapportert opsjonsforpliktelse
-- og trakk deretter den daglige opsjonsforpliktelsen fra én gang til. Det ga i
-- praksis dobbel fradragseffekt mellom 31.12.2025 og 30.06.2026.

UPDATE other_net_assets_daily_estimates
SET
    base_amount_usd = CAST(
        (
            SELECT
                CAST(s.base_other_net_assets_ex_option_reported AS REAL)
                + (
                    CAST(e.base_other_net_assets_ex_option_reported AS REAL)
                    - CAST(s.base_other_net_assets_ex_option_reported AS REAL)
                )
                * (
                    julianday(other_net_assets_daily_estimates.estimate_date)
                    - julianday(s.as_of_date)
                )
                / (julianday(e.as_of_date) - julianday(s.as_of_date))
            FROM other_net_assets_reported_anchors s
            CROSS JOIN other_net_assets_reported_anchors e
            WHERE s.as_of_date = '2025-12-31'
              AND e.as_of_date = '2026-06-30'
            LIMIT 1
        ) AS TEXT
    ),
    base_amount_nok = CAST(
        (
            SELECT
                (
                    CAST(s.base_other_net_assets_ex_option_reported AS REAL)
                    + (
                        CAST(e.base_other_net_assets_ex_option_reported AS REAL)
                        - CAST(s.base_other_net_assets_ex_option_reported AS REAL)
                    )
                    * (
                        julianday(other_net_assets_daily_estimates.estimate_date)
                        - julianday(s.as_of_date)
                    )
                    / (julianday(e.as_of_date) - julianday(s.as_of_date))
                )
                * CAST(other_net_assets_daily_estimates.usd_nok_rate AS REAL)
            FROM other_net_assets_reported_anchors s
            CROSS JOIN other_net_assets_reported_anchors e
            WHERE s.as_of_date = '2025-12-31'
              AND e.as_of_date = '2026-06-30'
            LIMIT 1
        ) AS TEXT
    ),
    amount_nok = CAST(
        (
            SELECT
                (
                    CAST(s.base_other_net_assets_ex_option_reported AS REAL)
                    + (
                        CAST(e.base_other_net_assets_ex_option_reported AS REAL)
                        - CAST(s.base_other_net_assets_ex_option_reported AS REAL)
                    )
                    * (
                        julianday(other_net_assets_daily_estimates.estimate_date)
                        - julianday(s.as_of_date)
                    )
                    / (julianday(e.as_of_date) - julianday(s.as_of_date))
                )
                * CAST(other_net_assets_daily_estimates.usd_nok_rate AS REAL)
                + CAST(other_net_assets_daily_estimates.associated_receivable_nok AS REAL)
                - CAST(other_net_assets_daily_estimates.option_liability_nok AS REAL)
            FROM other_net_assets_reported_anchors s
            CROSS JOIN other_net_assets_reported_anchors e
            WHERE s.as_of_date = '2025-12-31'
              AND e.as_of_date = '2026-06-30'
            LIMIT 1
        ) AS TEXT
    ),
    amount_usd = CAST(
        (
            SELECT
                (
                    (
                        CAST(s.base_other_net_assets_ex_option_reported AS REAL)
                        + (
                            CAST(e.base_other_net_assets_ex_option_reported AS REAL)
                            - CAST(s.base_other_net_assets_ex_option_reported AS REAL)
                        )
                        * (
                            julianday(other_net_assets_daily_estimates.estimate_date)
                            - julianday(s.as_of_date)
                        )
                        / (julianday(e.as_of_date) - julianday(s.as_of_date))
                    )
                    * CAST(other_net_assets_daily_estimates.usd_nok_rate AS REAL)
                    + CAST(other_net_assets_daily_estimates.associated_receivable_nok AS REAL)
                    - CAST(other_net_assets_daily_estimates.option_liability_nok AS REAL)
                )
                / CAST(other_net_assets_daily_estimates.usd_nok_rate AS REAL)
            FROM other_net_assets_reported_anchors s
            CROSS JOIN other_net_assets_reported_anchors e
            WHERE s.as_of_date = '2025-12-31'
              AND e.as_of_date = '2026-06-30'
            LIMIT 1
        ) AS TEXT
    ),
    inputs_hash = 'repair-post-grant-ona-v1:' || estimate_date,
    notes = 'Historical ONA repaired: post-grant base ONA is interpolated excluding the cash-settled option liability.',
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE estimate_date > '2025-12-31'
  AND estimate_date < '2026-06-30'
  AND quality = 'INTERPOLATED'
  AND EXISTS (
      SELECT 1
      FROM other_net_assets_reported_anchors s
      CROSS JOIN other_net_assets_reported_anchors e
      WHERE s.as_of_date = '2025-12-31'
        AND e.as_of_date = '2026-06-30'
        AND s.base_other_net_assets_ex_option_reported IS NOT NULL
        AND e.base_other_net_assets_ex_option_reported IS NOT NULL
  );

-- FULL NAV lagrer ONA-beløpet i selve snapshot-raden. Oppdater den historiske
-- totalen og NAV/aksje med differansen mot den reparerte daglige ONA-raden.
-- components_json beholdes fordi opsjonsinputene der ikke endres; markert
-- inputs_hash gjør at en senere ordinær refresh vil skrive hele snapshotet på ny.

UPDATE nav_snapshots
SET
    nav_total_nok = CAST(
        CAST(nav_total_nok AS REAL)
        - CAST(other_net_assets_nok AS REAL)
        + (
            SELECT CAST(o.amount_nok AS REAL)
            FROM other_net_assets_daily_estimates o
            WHERE o.estimate_date = substr(nav_snapshots.as_of_at, 1, 10)
        )
        AS TEXT
    ),
    nav_per_share_nok = CAST(
        (
            CAST(nav_total_nok AS REAL)
            - CAST(other_net_assets_nok AS REAL)
            + (
                SELECT CAST(o.amount_nok AS REAL)
                FROM other_net_assets_daily_estimates o
                WHERE o.estimate_date = substr(nav_snapshots.as_of_at, 1, 10)
            )
        ) / CAST(shares_outstanding AS REAL)
        AS TEXT
    ),
    discount_pct = CASE
        WHEN otec_price_nok IS NULL THEN NULL
        ELSE CAST(
            (
                1.0
                - CAST(otec_price_nok AS REAL)
                / (
                    (
                        CAST(nav_total_nok AS REAL)
                        - CAST(other_net_assets_nok AS REAL)
                        + (
                            SELECT CAST(o.amount_nok AS REAL)
                            FROM other_net_assets_daily_estimates o
                            WHERE o.estimate_date = substr(nav_snapshots.as_of_at, 1, 10)
                        )
                    ) / CAST(shares_outstanding AS REAL)
                )
            ) * 100.0
            AS TEXT
        )
    END,
    other_net_assets_nok = (
        SELECT o.amount_nok
        FROM other_net_assets_daily_estimates o
        WHERE o.estimate_date = substr(nav_snapshots.as_of_at, 1, 10)
    ),
    inputs_hash = 'repair-post-grant-ona-v1:' || as_of_at
WHERE calculation_version = 'full-market-nav-daily-v2'
  AND nav_scope = 'FULL'
  AND substr(as_of_at, 1, 10) > '2025-12-31'
  AND substr(as_of_at, 1, 10) < '2026-06-30'
  AND EXISTS (
      SELECT 1
      FROM other_net_assets_daily_estimates o
      WHERE o.estimate_date = substr(nav_snapshots.as_of_at, 1, 10)
  );
