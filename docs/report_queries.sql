-- name: listing_cases_by_exchange
SELECT e.name AS exchange,
       COUNT(*) AS cases,
       ROUND(AVG(COALESCE(lc.profit_pct, 0)), 2) AS avg_profit,
       SUM(CASE WHEN lc.profit_pct > 0 THEN 1 ELSE 0 END) AS wins
FROM listing_cases lc
JOIN exchanges e ON lc.exchange_id = e.id
GROUP BY e.name
ORDER BY cases DESC;

-- name: listing_cases_by_type
SELECT lc.listing_type,
       COUNT(*) AS cases,
       ROUND(AVG(COALESCE(lc.profit_pct, 0)), 2) AS avg_profit
FROM listing_cases lc
GROUP BY lc.listing_type
ORDER BY cases DESC;

-- name: top_profit_cases
SELECT a.symbol, e.name AS exchange, lc.case_date, lc.profit_pct, lc.result_label
FROM listing_cases lc
JOIN assets a ON lc.asset_id = a.id
JOIN exchanges e ON lc.exchange_id = e.id
WHERE lc.profit_pct IS NOT NULL
ORDER BY lc.profit_pct DESC
LIMIT 20;

-- name: premium_distribution
SELECT
  CASE
    WHEN lc.max_premium_pct IS NULL THEN 'unknown'
    WHEN lc.max_premium_pct < 1 THEN '<1%'
    WHEN lc.max_premium_pct < 3 THEN '1-3%'
    WHEN lc.max_premium_pct < 5 THEN '3-5%'
    WHEN lc.max_premium_pct < 10 THEN '5-10%'
    ELSE '>=10%'
  END AS premium_bucket,
  COUNT(*) AS cases
FROM listing_cases lc
GROUP BY premium_bucket
ORDER BY cases DESC;

-- name: cases_by_month
SELECT SUBSTR(lc.case_date, 1, 7) AS month,
       COUNT(*) AS cases,
       ROUND(AVG(COALESCE(lc.profit_pct, 0)), 2) AS avg_profit
FROM listing_cases lc
WHERE lc.case_date IS NOT NULL
GROUP BY SUBSTR(lc.case_date, 1, 7)
ORDER BY month;
