ALTER TABLE source_clicks
ADD COLUMN content TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS customer_touches (
  customer_id TEXT NOT NULL,
  click_id TEXT NOT NULL,
  bound_at INTEGER NOT NULL,
  PRIMARY KEY (customer_id, click_id),
  FOREIGN KEY (click_id) REFERENCES source_clicks(click_id)
);

CREATE INDEX IF NOT EXISTS idx_customer_touches_customer_bound
  ON customer_touches(customer_id, bound_at);

CREATE INDEX IF NOT EXISTS idx_customer_touches_click
  ON customer_touches(click_id);
