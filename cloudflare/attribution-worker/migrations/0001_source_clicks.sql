CREATE TABLE IF NOT EXISTS source_clicks (
  click_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  medium TEXT NOT NULL,
  campaign TEXT NOT NULL,
  path TEXT NOT NULL,
  country TEXT NOT NULL DEFAULT '',
  clicked_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s', 'now') AS INTEGER) * 1000)
);

CREATE INDEX IF NOT EXISTS idx_source_clicks_clicked_at
  ON source_clicks(clicked_at);

CREATE INDEX IF NOT EXISTS idx_source_clicks_source_campaign
  ON source_clicks(source, campaign, clicked_at);
