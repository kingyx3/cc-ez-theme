-- `clicked_at` is the canonical click event timestamp used by both Contact and
-- Order attribution. The write-time `created_at` default from the original
-- schema is never read, so keeping it duplicates timestamp storage on every row.
ALTER TABLE source_clicks DROP COLUMN created_at;

-- Attribution queries are customer-first and use the composite
-- (customer_id, bound_at) index. No runtime path looks up customer_touches by
-- click_id alone, so this secondary index only adds write/storage overhead.
DROP INDEX IF EXISTS idx_customer_touches_click;
