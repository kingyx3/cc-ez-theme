-- Advertising-network click identifiers are not attribution keys. The Worker UUID
-- remains the internal source_clicks/customer_touches join key, while this table
-- preserves the vendor identifiers needed by HubSpot and the ad platforms.
CREATE TABLE IF NOT EXISTS source_click_identifiers (
  click_id TEXT NOT NULL,
  network TEXT NOT NULL,
  parameter TEXT NOT NULL,
  identifier TEXT NOT NULL,
  PRIMARY KEY (click_id, parameter),
  FOREIGN KEY (click_id) REFERENCES source_clicks(click_id)
);

-- The primary key already supports the runtime join from source_clicks by
-- click_id. This index supports audits/backfills by vendor parameter without
-- duplicating the full identifier value in a second index.
CREATE INDEX IF NOT EXISTS idx_source_click_identifiers_parameter
  ON source_click_identifiers(parameter, click_id);
