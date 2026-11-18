-- Q1: order payment approval rate, not visitor conversion.
SELECT c.campaign_name,
       COUNT(*) AS order_count,
       SUM(CASE WHEN p.status = 'approved' THEN 1 ELSE 0 END) AS approved_orders,
       ROUND(100.0 * SUM(CASE WHEN p.status = 'approved' THEN 1 ELSE 0 END)
             / COUNT(*), 2) AS approval_rate_pct
FROM demo_orders o
JOIN demo_campaigns c ON c.campaign_id = o.campaign_id
JOIN demo_payments p ON p.order_id = o.order_id
GROUP BY c.campaign_id, c.campaign_name
ORDER BY c.campaign_id;

-- Q2: aggregate flags before joins to avoid multiplying returns by tickets.
WITH returned AS (
    SELECT DISTINCT order_id FROM demo_returns
), contacted AS (
    SELECT DISTINCT order_id FROM demo_support_tickets
)
SELECT s.delayed,
       COUNT(*) AS shipped_orders,
       SUM(CASE WHEN r.order_id IS NOT NULL THEN 1 ELSE 0 END) AS returned_orders,
       SUM(CASE WHEN t.order_id IS NOT NULL THEN 1 ELSE 0 END) AS contacted_orders,
       ROUND(100.0 * SUM(CASE WHEN r.order_id IS NOT NULL THEN 1 ELSE 0 END)
             / COUNT(*), 2) AS return_rate_pct,
       ROUND(100.0 * SUM(CASE WHEN t.order_id IS NOT NULL THEN 1 ELSE 0 END)
             / COUNT(*), 2) AS contact_rate_pct
FROM demo_shipments s
LEFT JOIN returned r ON r.order_id = s.order_id
LEFT JOIN contacted t ON t.order_id = s.order_id
GROUP BY s.delayed
ORDER BY s.delayed;

-- Q3: gross approved sales before refunds; return rate uses shipped orders.
SELECT pr.product_name,
       SUM(CASE WHEN p.status = 'approved'
                THEN i.quantity * i.unit_price_krw ELSE 0 END) AS revenue_krw,
       SUM(CASE WHEN s.order_id IS NOT NULL THEN 1 ELSE 0 END) AS shipped_orders,
       SUM(CASE WHEN r.order_id IS NOT NULL THEN 1 ELSE 0 END) AS returned_orders,
       ROUND(100.0 * SUM(CASE WHEN r.order_id IS NOT NULL THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN s.order_id IS NOT NULL THEN 1 ELSE 0 END), 0), 2)
             AS return_rate_pct
FROM demo_order_items i
JOIN demo_products pr ON pr.product_id = i.product_id
JOIN demo_payments p ON p.order_id = i.order_id
LEFT JOIN demo_shipments s ON s.order_id = i.order_id
LEFT JOIN demo_returns r ON r.order_id = i.order_id AND r.product_id = i.product_id
GROUP BY pr.product_id, pr.product_name
ORDER BY pr.product_id;
