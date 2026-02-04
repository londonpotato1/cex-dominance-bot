-- Core reference tables
CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  name TEXT,
  chain TEXT,
  contract_address TEXT,
  decimals INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exchanges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  tier TEXT,
  country TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Listing events (announcements)
CREATE TABLE IF NOT EXISTS listing_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL,
  exchange_id INTEGER NOT NULL,
  listing_type TEXT,
  announce_ts TEXT,
  listing_ts TEXT,
  deposit_open_ts TEXT,
  withdrawal_open_ts TEXT,
  source TEXT,
  status TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (asset_id) REFERENCES assets(id),
  FOREIGN KEY (exchange_id) REFERENCES exchanges(id)
);

-- Normalized listing case reviews (guide/telegram/manual)
CREATE TABLE IF NOT EXISTS listing_cases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL,
  exchange_id INTEGER NOT NULL,
  case_date TEXT,
  listing_type TEXT,
  result_label TEXT,
  profit_pct REAL,
  market_cap_usd REAL,
  deposit_krw REAL,
  max_premium_pct REAL,
  hedge_type TEXT,
  hot_wallet_usd REAL,
  network_chain TEXT,
  withdrawal_open TEXT,
  notes TEXT,
  source TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (asset_id) REFERENCES assets(id),
  FOREIGN KEY (exchange_id) REFERENCES exchanges(id)
);

-- Market snapshots (spot)
CREATE TABLE IF NOT EXISTS market_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL,
  exchange_id INTEGER NOT NULL,
  ts TEXT NOT NULL,
  price REAL,
  volume_1m_krw REAL,
  volume_5m_krw REAL,
  premium_pct REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (asset_id) REFERENCES assets(id),
  FOREIGN KEY (exchange_id) REFERENCES exchanges(id)
);

-- Futures funding and OI snapshots
CREATE TABLE IF NOT EXISTS funding_rates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL,
  exchange_id INTEGER NOT NULL,
  ts TEXT NOT NULL,
  funding_rate REAL,
  open_interest REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (asset_id) REFERENCES assets(id),
  FOREIGN KEY (exchange_id) REFERENCES exchanges(id)
);

-- Hot wallets
CREATE TABLE IF NOT EXISTS hot_wallets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  exchange_id INTEGER NOT NULL,
  chain TEXT,
  address TEXT NOT NULL,
  label TEXT,
  first_seen_ts TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (exchange_id) REFERENCES exchanges(id)
);

-- Wallet flows (deposit/withdraw)
CREATE TABLE IF NOT EXISTS wallet_flows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  exchange_id INTEGER NOT NULL,
  asset_id INTEGER NOT NULL,
  chain TEXT,
  address TEXT,
  direction TEXT,
  amount REAL,
  usd_value REAL,
  tx_hash TEXT,
  ts TEXT,
  source TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (exchange_id) REFERENCES exchanges(id),
  FOREIGN KEY (asset_id) REFERENCES assets(id)
);

-- DEX liquidity snapshots
CREATE TABLE IF NOT EXISTS dex_liquidity_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL,
  chain TEXT,
  dex_name TEXT,
  ts TEXT,
  liquidity_usd REAL,
  volume_24h_usd REAL,
  pool_count INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (asset_id) REFERENCES assets(id)
);

-- Notice events (non-listing included)
CREATE TABLE IF NOT EXISTS notice_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  exchange_id INTEGER NOT NULL,
  notice_type TEXT,
  title TEXT,
  symbols TEXT,
  notice_ts TEXT,
  source TEXT,
  severity TEXT,
  action TEXT,
  raw_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (exchange_id) REFERENCES exchanges(id)
);

-- Listing outcomes (post-listing metrics)
CREATE TABLE IF NOT EXISTS listing_outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_event_id INTEGER NOT NULL,
  asset_id INTEGER NOT NULL,
  exchange_id INTEGER NOT NULL,
  start_ts TEXT,
  end_ts TEXT,
  start_price REAL,
  peak_price REAL,
  peak_ts TEXT,
  pump_pct REAL,
  deposit_usd REAL,
  deposit_krw REAL,
  market_cap_usd REAL,
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (listing_event_id) REFERENCES listing_events(id),
  FOREIGN KEY (asset_id) REFERENCES assets(id),
  FOREIGN KEY (exchange_id) REFERENCES exchanges(id)
);

-- Signals and alerts
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL,
  exchange_id INTEGER NOT NULL,
  ts TEXT,
  signal_type TEXT,
  score REAL,
  features_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (asset_id) REFERENCES assets(id),
  FOREIGN KEY (exchange_id) REFERENCES exchanges(id)
);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  signal_id INTEGER NOT NULL,
  sent_ts TEXT,
  channel TEXT,
  status TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_listing_events_asset_exchange ON listing_events(asset_id, exchange_id);
CREATE INDEX IF NOT EXISTS idx_listing_cases_asset_exchange ON listing_cases(asset_id, exchange_id);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_ts ON market_snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_funding_rates_ts ON funding_rates(ts);
CREATE INDEX IF NOT EXISTS idx_wallet_flows_ts ON wallet_flows(ts);
CREATE INDEX IF NOT EXISTS idx_notice_events_ts ON notice_events(notice_ts);
CREATE INDEX IF NOT EXISTS idx_listing_outcomes_event ON listing_outcomes(listing_event_id);
