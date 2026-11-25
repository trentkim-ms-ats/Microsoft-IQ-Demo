-- Q1: one order per campaign, success takes precedence over failed attempts.
WITH payment_flags AS (
  SELECT order_id,
         MAX(CASE WHEN UPPER(TRIM(payment_status)) IN ('SUCCESS','RETRYSUCCESS') THEN 1 ELSE 0 END) AS approved,
         MAX(CASE WHEN UPPER(TRIM(payment_status)) = 'FAILED' THEN 1 ELSE 0 END) AS failed
  FROM workshop_payments GROUP BY order_id
), attributed AS (
  SELECT DISTINCT campaign_id, order_id FROM workshop_campaign_attribution
)
SELECT c.campaign_id, c.campaign_name, COUNT(*) AS order_count,
       SUM(COALESCE(p.approved, 0)) AS approved_orders,
       SUM(CASE WHEN COALESCE(p.approved, 0) = 0 AND p.failed = 1 THEN 1 ELSE 0 END) AS failed_orders,
       SUM(CASE WHEN COALESCE(p.approved, 0) = 0 AND COALESCE(p.failed, 0) = 0 THEN 1 ELSE 0 END) AS unknown_orders,
       ROUND(100.0 * SUM(COALESCE(p.approved, 0)) / COUNT(*), 2) AS approval_rate_pct
FROM attributed a
JOIN workshop_campaigns c ON c.campaign_id = a.campaign_id
LEFT JOIN payment_flags p ON p.order_id = a.order_id
WHERE EXISTS (SELECT 1 FROM workshop_orders o WHERE o.order_id = a.order_id)
GROUP BY c.campaign_id, c.campaign_name ORDER BY c.campaign_id;

-- Q2: order-level flags avoid multiplication from multiple returns or tickets.
WITH shipment_flags AS (
  SELECT order_id, MAX(CASE WHEN UPPER(TRIM(shipment_status)) = 'DELAYED' THEN 1 ELSE 0 END) AS delayed
  FROM workshop_shipments GROUP BY order_id
), returned AS (
  SELECT DISTINCT order_id FROM workshop_returns
), complaints AS (
  SELECT DISTINCT order_id FROM workshop_support_tickets
  WHERE UPPER(TRIM(ticket_type)) = 'COMPLAINT'
), orders AS (
  SELECT DISTINCT order_id FROM workshop_orders
)
SELECT s.delayed, COUNT(*) AS orders_count,
       SUM(CASE WHEN r.order_id IS NOT NULL THEN 1 ELSE 0 END) AS returned_orders,
       SUM(CASE WHEN t.order_id IS NOT NULL THEN 1 ELSE 0 END) AS complaint_orders,
       ROUND(100.0 * SUM(CASE WHEN r.order_id IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS return_rate_pct,
       ROUND(100.0 * SUM(CASE WHEN t.order_id IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS complaint_rate_pct
FROM shipment_flags s JOIN orders o ON o.order_id = s.order_id
LEFT JOIN returned r ON r.order_id = s.order_id
LEFT JOIN complaints t ON t.order_id = s.order_id
GROUP BY s.delayed ORDER BY s.delayed;

-- Q3: net/gross is a discount proxy, not cost-based gross margin.
WITH unique_orders AS (
  SELECT DISTINCT order_id, customer_id, gross_amount, net_amount FROM workshop_orders
), repeat_customers AS (
  SELECT customer_id, CASE WHEN COUNT(DISTINCT order_id) >= 2 THEN 1 ELSE 0 END AS is_repeat
  FROM unique_orders GROUP BY customer_id
), promotion_orders AS (
  SELECT DISTINCT op.order_id, p.promotion_type
  FROM workshop_order_promotions op JOIN workshop_promotions p ON p.promotion_id = op.promotion_id
)
SELECT po.promotion_type, COUNT(*) AS orders_count,
       ROUND(1.0 * SUM(CAST(o.net_amount AS FLOAT)) / NULLIF(SUM(CAST(o.gross_amount AS FLOAT)), 0), 4) AS net_to_gross,
       ROUND(100.0 * AVG(rc.is_repeat), 2) AS repeat_customer_pct
FROM promotion_orders po JOIN unique_orders o ON o.order_id = po.order_id
JOIN repeat_customers rc ON rc.customer_id = o.customer_id
GROUP BY po.promotion_type ORDER BY po.promotion_type;

-- Q4: ever-stockout product flag; snapshot date is not matched to order date.
WITH stockout_products AS (
  SELECT DISTINCT product_id FROM workshop_inventory_snapshots
  WHERE CAST(on_hand_qty AS FLOAT) - CAST(reserved_qty AS FLOAT) <= 0
), order_flags AS (
  SELECT o.order_id,
         MAX(CASE WHEN sp.product_id IS NOT NULL THEN 1 ELSE 0 END) AS has_stockout_product,
         MAX(CASE WHEN UPPER(TRIM(o.order_status)) IN ('CANCELLED','CANCELED') THEN 1 ELSE 0 END) AS cancelled
  FROM workshop_orders o JOIN workshop_order_items i ON i.order_id = o.order_id
  LEFT JOIN stockout_products sp ON sp.product_id = i.product_id GROUP BY o.order_id
), ticket_counts AS (
  SELECT order_id, COUNT(*) AS ticket_count FROM workshop_support_tickets GROUP BY order_id
)
SELECT f.has_stockout_product, COUNT(*) AS orders_count,
       ROUND(100.0 * AVG(f.cancelled), 2) AS cancellation_rate_pct,
       ROUND(AVG(COALESCE(t.ticket_count, 0) * 1.0), 2) AS tickets_per_order
FROM order_flags f LEFT JOIN ticket_counts t ON t.order_id = f.order_id
GROUP BY f.has_stockout_product ORDER BY f.has_stockout_product;

-- Q5: repeat means two or more orders overall, not necessarily after return.
WITH unique_orders AS (
  SELECT DISTINCT order_id, customer_id, channel_id FROM workshop_orders
), repeat_customers AS (
  SELECT customer_id, CASE WHEN COUNT(DISTINCT order_id) >= 2 THEN 1 ELSE 0 END AS is_repeat
  FROM unique_orders GROUP BY customer_id
), segments AS (
  SELECT DISTINCT ch.channel_name, c.customer_tier, r.return_reason, o.customer_id
  FROM workshop_returns r JOIN unique_orders o ON o.order_id = r.order_id AND o.customer_id = r.customer_id
  JOIN workshop_customers c ON c.customer_id = o.customer_id
  JOIN workshop_channels ch ON ch.channel_id = o.channel_id
)
SELECT s.channel_name, s.customer_tier, s.return_reason, COUNT(*) AS customers_count,
       ROUND(100.0 * AVG(rc.is_repeat), 2) AS repeat_customer_pct
FROM segments s JOIN repeat_customers rc ON rc.customer_id = s.customer_id
GROUP BY s.channel_name, s.customer_tier, s.return_reason
ORDER BY s.channel_name, s.customer_tier, s.return_reason;
