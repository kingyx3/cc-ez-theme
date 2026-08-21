-- Link-preview crawlers and browser prefetches reach /go/* constantly, and every
-- one of them was counted as a click. They are still recorded, so the row count
-- stays complete, but they carry the reason they were judged automated and a
-- channel report can subtract them.
ALTER TABLE source_clicks ADD COLUMN bot INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_clicks ADD COLUMN bot_reason TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_source_clicks_human
  ON source_clicks(bot, clicked_at);
