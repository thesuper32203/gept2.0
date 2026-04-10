# gept2.0 — OSRS Grand Exchange Flipping Tool with AI

## Context

Existing OSRS flipping tools have gaps: **Flipping Copilot** hides its ML behind a closed backend (you can't see or customize the model), and **GePT** has a solid open ML pipeline but focuses on medium-to-long-term predictions (1h-48h), missing the short-term window (<1h) where active flippers operate. Both lack a transparent, end-to-end pipeline that a solo developer can own and iterate on.

**gept2.0** will be a ground-up OSRS GE flipping platform with a clear pipeline: **Collect → Analyze → Predict → Recommend → Display**. It focuses on two play styles: **short-term active flips (15min-1h)** and **overnight passive flips (8-48h)**. Web dashboard first, Discord bot later.

### Developer Context
- Python intermediate (comfortable with syntax, still building class/OOP skills)
- No ML experience — every ML concept, library, and design choice will be thoroughly documented with inline comments and companion docs explaining **what** each piece does and **why** we chose it
- No Docker experience — each phase includes step-by-step setup instructions, not just code
- All code will be well-commented and modular so each piece can be understood independently

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Backend API** | Python + FastAPI | Best ML ecosystem, proven by GePT |
| **Database** | PostgreSQL + TimescaleDB | Time-series optimized, hypertables for price data |
| **ML Framework** | XGBoost / LightGBM / scikit-learn | Gradient boosted models — proven best-in-class for tabular financial data, faster to train and iterate than deep learning |
| **Task Scheduler** | APScheduler | Lightweight scheduled jobs, no Redis needed — simpler than Celery for a solo project |
| **Frontend** | Next.js (React) | Rich dashboard, SSR for fast loads — large community for learning |
| **Discord Bot** | discord.py | Phase 5 — deliver recommendations to Discord channels |
| **Containerization** | Docker Compose | Orchestrate DB, collectors, API, frontend in one command |
| **Package Manager** | Poetry (Python), pnpm (JS) | Dependency management, reproducible installs |
| **Documentation** | Inline comments + `/docs` folder | Every module gets a companion doc explaining concepts |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                  Docker Compose                  │
├──────────┬──────────┬──────────┬────────────────┤
│Collectors│  ML       │  API     │  Frontend      │
│(scheduled│  Engine   │ (FastAPI)│  (Next.js)     │
│ polling) │(features +│          │                │
│          │ GBDT     )│          │                │
├──────────┴──────────┴────┬─────┴────────────────┤
│          PostgreSQL + TimescaleDB               │
│  prices_5min | prices_1hr | items               │
│  predictions | recommendations | users          │
└─────────────────────────────────────────────────┘
```

---

## Phase 0: Environment Setup (Before Any Code)

**Goal:** Get your machine ready to run the project. We'll walk through every step together when you're ready to build.

### What You Need to Install (one-time)

1. **Docker Desktop** — runs all our services (DB, collectors, API, frontend) in isolated containers
   - Download from docker.com, install like any app
   - This is the only thing that needs to be installed globally — everything else runs inside Docker

2. **VS Code** — you likely already have this
   - Extensions to add: Python, Docker, Pylance

3. **Git** — for version control (saving your work history)
   - Likely already installed; we'll initialize a repo in the project folder

### What Docker Does For You

Think of Docker like a shipping container for software. Instead of installing Python, PostgreSQL, Node.js etc. directly on your Windows machine (and fighting version conflicts), Docker runs each service in its own isolated "container" — a mini virtual machine that already has everything it needs.

```
Without Docker:               With Docker:
Install Python ✗              docker compose up ✓
Install PostgreSQL ✗          (everything starts automatically)
Install Node.js ✗
Configure each to talk ✗
Fight version conflicts ✗
```

### Project Initialization Checklist
- [ ] Install Docker Desktop
- [ ] Create `gept2.0/` folder structure
- [ ] Initialize git repo (`git init`)
- [ ] Create `docker-compose.yml` (defines all services)
- [ ] Create `.env` file (database passwords, API keys — never committed to git)
- [ ] Create `packages/` subfolders
- [ ] Verify Docker is working: `docker compose up db` starts the database

### How You'll Run the Project Day-to-Day

```bash
# Start everything
docker compose up

# Start just the database (useful early on)
docker compose up db

# Stop everything
docker compose down

# See logs from a specific service
docker compose logs -f collector
```

You won't need to memorize these — we'll set up a simple script and walk through each command when we get there.

---

## Phase 1: Data Collection (Week 1-2)

**Goal:** Reliable, continuous OSRS GE price data collection and storage.

### Tasks
1. **Initialize project** — monorepo structure, Docker Compose, Poetry/pnpm setup
2. **Database schema** — TimescaleDB hypertables for multi-resolution price data
3. **OSRS Wiki API collectors** — 2 polling services:
   - `collector_5min` — 5-min OHLC every 300s (primary ML data)
   - `collector_1hr` — 1-hour averages every 3600s
4. **Item metadata** — fetch and cache item names, buy limits, members status
5. **Backfill script** — pull historical data to bootstrap ML training
6. **Health monitoring** — circuit breaker, retry logic, collection gap detection

### Key Data Source
- OSRS Wiki API: `https://prices.runescape.wiki/api/v1/osrs/`
  - `/5m` — 5-minute OHLC (avg high/low price + volume per item)
  - `/1h` — 1-hour averages
  - `/timeseries?id=<item>&timestep=5m` — historical data for backfill
  - `/mapping` — item metadata (name, buy limit, members, etc.)

### Database Tables
```sql
-- TimescaleDB hypertable (auto-partitions by time for fast queries)
CREATE TABLE prices_5min (
    time        TIMESTAMPTZ NOT NULL,
    item_id     INT NOT NULL,
    avg_high    BIGINT,     -- avg instant-buy price (what buyers pay)
    avg_low     BIGINT,     -- avg instant-sell price (what sellers receive)
    high_vol    INT,        -- number of items bought at high price
    low_vol     INT         -- number of items sold at low price
);
SELECT create_hypertable('prices_5min', 'time');
-- Same structure for prices_1hr
```

### Borrow from GePT
- Circuit breaker pattern with exponential backoff
- Multi-resolution collection strategy (5min/1hr)
- TimescaleDB hypertables
- Timeseries endpoint for historical backfill

### Project Structure (full project — built incrementally)
```
gept2.0/
├── PRD.md
├── docker-compose.yml
├── docs/                       # Companion documentation
│   ├── setup-guide.md          # How to run the project
│   ├── data-pipeline.md        # How data collection works and why
│   ├── ml-explained.md         # ML concepts in plain language
│   ├── recommendation-logic.md # How flips are scored and ranked
│   └── api-reference.md        # API endpoint docs
├── packages/
│   ├── collector/              # Phase 1 — data collection
│   │   ├── collectors/
│   │   │   ├── prices_5min.py  # Polls /5m endpoint every 300s
│   │   │   ├── prices_1hr.py   # Polls /1h endpoint every 3600s
│   │   │   └── items.py        # Item metadata sync (/mapping)
│   │   ├── db/
│   │   │   ├── schema.sql      # TimescaleDB tables
│   │   │   └── connection.py   # DB connection helper
│   │   └── backfill.py         # Pull historical data
│   ├── engine/                 # Phase 2-3 — ML + recommendations
│   │   ├── features/           # Feature computation (per-item engineering)
│   │   ├── models/             # XGBoost, LightGBM, RF, LogReg
│   │   ├── training/           # Training pipeline + model comparison
│   │   ├── evaluation/         # Metrics, calibration, backtesting
│   │   ├── inference/          # Prediction service (runs every 5min)
│   │   └── recommendations/    # Scoring + filtering
│   ├── api/                    # Phase 3 — FastAPI backend
│   ├── web/                    # Phase 4 — Next.js dashboard
│   └── bot/                    # Phase 5 — Discord bot
├── pyproject.toml
└── README.md
```

---

## Phase 2: Feature Engineering & ML Model (Week 3-5)

**Goal:** Build a feature-engineered ML pipeline that predicts short-term price movement and order fill probability for OSRS Grand Exchange items. Every step documented so you understand what the model does and why.

**Why gradient boosted models instead of transformers?** For tabular financial data with engineered features, gradient boosted decision trees (XGBoost, LightGBM) consistently outperform deep learning approaches. They train faster, require less data, are easier to debug, and produce interpretable feature importances. GePT proved transformers can work for OSRS data, but we can achieve equal or better results with a simpler, more maintainable approach.

### 2A: Feature Engine (Week 3)

All features are computed **per item_id** — always group by item_id and sort by timestamp before computing lag or rolling features. The dataset contains ~4,000 tradable items with millions of rows.

**Raw fields from database:**
- `item_id`, `timestamp`, `avg_high_price`, `avg_low_price`, `high_volume`, `low_volume`

#### Base Derived Variables

| Feature | Formula | Why it matters |
|---------|---------|----------------|
| `mid_price` | `(avg_high_price + avg_low_price) / 2` | Central reference price for all calculations |
| `spread` | `avg_high_price - avg_low_price` | The fundamental flip margin |
| `volume_total` | `high_volume + low_volume` | Total trading activity |
| `spread_pct` | `spread / mid_price` | Normalized spread — comparable across items of different price |
| `volume_imbalance` | `(high_volume - low_volume) / volume_total` | Buy/sell pressure — imbalance signals demand shifts |

#### Lag Features

Capture recent state at specific lookback points:

| Feature | Description |
|---------|-------------|
| `price_lag1` through `price_lag20` | `mid_price` at t-1, t-5, t-10, t-20 |
| `volume_lag1`, `volume_lag5` | `volume_total` at t-1, t-5 |
| `spread_lag1`, `spread_lag5` | `spread` at t-1, t-5 |

#### Return Features (Momentum)

How much price changed over recent windows — captures momentum and mean reversion:

| Feature | Formula |
|---------|---------|
| `return_1` | `(mid_price - price_lag1) / price_lag1` |
| `return_5` | `(mid_price - price_lag5) / price_lag5` |
| `return_10` | `(mid_price - price_lag10) / price_lag10` |
| `return_20` | `(mid_price - price_lag20) / price_lag20` |

#### Moving Averages & Trend Signals

| Feature | Formula | Purpose |
|---------|---------|---------|
| `ma_5`, `ma_20`, `ma_60` | Rolling mean of `mid_price` | Smoothed trend at different time scales |
| `price_vs_ma5` | `mid_price / ma_5` | Is price above or below short-term average? |
| `price_vs_ma20` | `mid_price / ma_20` | Is price above or below medium-term average? |
| `ma5_vs_ma20` | `ma_5 / ma_20` | Crossover signal — short trend vs medium trend |

#### Volatility Features

How much price bounces around — high volatility = more opportunity but more risk:

| Feature | Formula |
|---------|---------|
| `volatility_5` | `rolling_std(return_1, 5)` |
| `volatility_20` | `rolling_std(return_1, 20)` |
| `volatility_60` | `rolling_std(return_1, 60)` |

#### Volume Features

| Feature | Formula | Purpose |
|---------|---------|---------|
| `volume_ma5`, `volume_ma20` | Rolling mean of `volume_total` | Baseline trading activity |
| `volume_ratio_5` | `volume_total / volume_ma5` | Short-term volume spike detection |
| `volume_ratio_20` | `volume_total / volume_ma20` | Medium-term volume spike detection |
| `volume_spike` | `volume_total / volume_ma20` | Abnormal volume flag |
| `imbalance_change` | `volume_imbalance - volume_imbalance(t-1)` | Shift in buy/sell pressure |

#### Spread Features

| Feature | Formula |
|---------|---------|
| `spread_pct` | `spread / mid_price` |
| `spread_ma5`, `spread_ma20` | Rolling mean of `spread` |
| `spread_change` | `spread - spread_lag1` |

#### Breakout Features

| Feature | Formula | Purpose |
|---------|---------|---------|
| `rolling_max_20` | `rolling_max(mid_price, 20)` | Recent price ceiling |
| `rolling_min_20` | `rolling_min(mid_price, 20)` | Recent price floor |
| `price_vs_max20` | `mid_price / rolling_max_20` | How close to recent high? |
| `price_vs_min20` | `mid_price / rolling_min_20` | How close to recent low? |

#### Time Features

Extract from timestamp and encode cyclically so the model understands that hour 23 is close to hour 0:

| Feature | Formula |
|---------|---------|
| `hour`, `day_of_week`, `is_weekend` | Direct extraction from timestamp |
| `hour_sin`, `hour_cos` | `sin(2π * hour / 24)`, `cos(2π * hour / 24)` |
| `dow_sin`, `dow_cos` | `sin(2π * day_of_week / 7)`, `cos(2π * day_of_week / 7)` |

#### Item-Level Features

Computed once per item — help the model understand liquidity and volatility differences between items:

| Feature | Description |
|---------|-------------|
| `item_avg_volume` | Mean `volume_total` for this item |
| `item_avg_spread` | Mean `spread` for this item |
| `item_volatility` | Std dev of `return_1` for this item |
| `item_avg_price` | Mean `mid_price` for this item |

### 2B: ML Models (Week 4)

**System goal:** Predict two things per item per timestep:
1. **Short-term price movement** — `future_return_5 = (mid_price(t+5) - mid_price) / mid_price`
2. **Order fill probability** — will an order placed at a given price fill within a short window?

#### Target Variables

| Target | Type | Definition |
|--------|------|------------|
| `future_return_5` | Regression | % price change over next 5 periods |
| `target_up` | Classification | `1` if `future_return_5 > threshold` |
| `target_fill` | Classification | `1` if future low price within window ≤ order price |

#### Models to Train & Compare

| Model | Library | Purpose |
|-------|---------|---------|
| **XGBoost** | `xgboost` | Primary candidate — best on structured tabular data |
| **LightGBM** | `lightgbm` | Faster training, handles large datasets well |
| **Random Forest** | `scikit-learn` | Simpler ensemble baseline |
| **Logistic Regression** | `scikit-learn` | Linear baseline — if this wins, features need work |

The best-performing model on validation + backtesting becomes the production model.

### 2C: Training Pipeline (Week 4-5)

1. Load raw data from database
2. Sort by `item_id` and `timestamp`
3. Generate all features per item
4. Drop rows with missing lag values (first N rows per item)
5. Time-based split — **no random shuffling** (would leak future data):
   - 70% train
   - 15% validation
   - 15% test
6. Train all 4 models, log metrics for comparison
7. Select best model

### 2D: Evaluation Metrics

| Metric | Target | What it tells you |
|--------|--------|-------------------|
| **Directional accuracy** | >55% | Does the model predict up/down correctly? |
| **MAE / RMSE** | Lower is better | How far off are regression predictions? |
| **Precision / Recall / F1** | Balanced | How good are classification predictions? |
| **ROC-AUC** | >0.6 | How well does the model separate positive/negative? |
| **Calibration** | Predicted probs ≈ actual rates | Are probability outputs trustworthy? |

### 2E: Profit Backtesting

Verify the model has real economic value with a simple backtest:

- If predicted return > threshold → **buy**
- If predicted return < negative threshold → **sell**

Track:
- Total profit (GP)
- Sharpe-like return (risk-adjusted)
- Maximum drawdown (worst losing streak)

### 2F: Inference Service

Runs every 5 minutes:

1. Pull latest market data from database
2. Compute features using latest window
3. Run model predictions for all ~4,000 items
4. Store predictions in database:
   - `item_id`, `timestamp`, `predicted_return`, `predicted_fill_probability`

These predictions power the recommendation engine in Phase 3.

### Key Advantages Over Transformer Approach
- **Faster iteration** — train in minutes, not hours
- **Interpretable** — feature importance tells you exactly what drives predictions
- **Proven on tabular data** — gradient boosted models consistently win Kaggle competitions on structured financial data
- **Simpler infrastructure** — no GPU required, runs on CPU
- **Easier debugging** — inspect individual features, not hidden attention weights

### Companion Doc: `docs/ml-explained.md`
Will contain: what is gradient boosting, how XGBoost works, what feature importance means, how to interpret predictions — all in plain language with OSRS examples

---

## Phase 3: Recommendation Engine + API (Week 5-7)

**Goal:** Turn predictions into actionable flip recommendations served via API.

### Tasks
1. **Recommendation engine** — scoring and filtering:
   - **Profit calc**: `profit = (sell - buy) * qty - tax` where `tax = floor(sell * 0.02)` capped at 5M
   - **EV calc**: `expected_profit = profit * fill_probability`
   - **ROI**: `roi = expected_profit / capital_required`
   - **Score**: weighted combo of ROI, confidence, fill probability, time-to-fill
2. **User constraint filtering**:
   - Available capital (GP budget)
   - Play style: Active (<1h flips), Hybrid (1-8h), Passive (8-48h)
   - Risk tolerance: Conservative / Balanced / Aggressive
   - Item blacklist/whitelist
3. **Capital allocation** — spread GP across multiple items, don't put all eggs in one basket
4. **FastAPI endpoints**:
   - `GET /api/recommendations` — filtered, scored flip suggestions
   - `GET /api/predictions/{item_id}` — raw predictions for an item
   - `GET /api/items` — searchable item list
   - `GET /api/history/{item_id}` — price history + prediction overlay
   - `GET /api/portfolio` — tracked flips and P&L
5. **Fill probability model** — estimate likelihood a GE offer fills at a given price/time

### Borrow from GePT
- Recommendation filtering by capital/style/risk
- EV-adjusted profit calculation
- Fill probability concept (now a dedicated classification model)
- Confidence tiers (High/Medium/Low) — derived from model prediction confidence

### Borrow from Flipping Copilot
- Flip lifecycle tracking (buy → waiting → sell → complete)
- Portfolio ROI calculation

---

## Phase 4: Web Dashboard (Week 7-9)

**Goal:** User-facing dashboard to view recommendations and track performance.

### Tasks
1. **Dashboard page** — top flip recommendations with filters
   - Card per recommendation: item, buy/sell price, expected profit, confidence, horizon
   - Filter controls: capital, style, risk
   - Sort by: ROI, profit, confidence, time
2. **Item detail page** — price chart with prediction overlay
   - Historical price chart (candlestick)
   - ML prediction bands (quantile ranges)
   - Volume bars
   - Key stats: spread, volatility, avg daily volume
3. **Portfolio tracker** — log flips, track P&L
   - Manual entry or import
   - Running total profit, ROI, win rate
4. **Settings** — user preferences, notification config
5. **Auth** — simple JWT auth (Discord OAuth optional later)

### Tech Details
- Next.js App Router
- Recharts or Lightweight Charts for price visualization
- TanStack Query for data fetching
- Tailwind CSS for styling

---

## Phase 5: Discord Bot & Extensions (Week 9+)

**Goal:** Deliver recommendations via Discord — the ultimate target platform.

### Tasks
1. **Discord bot** (discord.py):
   - `/flips` — get top recommendations with filters (capital, style)
   - `/track <item>` — watch an item, get alerts on price movement
   - `/portfolio` — see your tracked flips and P&L
   - Scheduled alerts: "Your overnight flip on Cannonballs is ready to sell"
   - Embed-style messages with item images, price charts
2. **Notification system** — price alerts, flip completion estimates
3. **Model retraining pipeline** — automated with new data on a schedule
4. **Backtesting framework** — evaluate strategy changes before going live

---

## Verification Plan

1. **Phase 1**: Query DB to confirm prices are being collected continuously. Check for gaps. Compare against Wiki API directly.
2. **Phase 2**: Run model evaluation — check directional accuracy >55%, calibration (predicted probabilities match actual rates), backtest profit > baseline (buy-low-sell-high without ML), and feature importance makes intuitive sense.
3. **Phase 3**: Hit API endpoints, verify recommendations make sense (positive EV, reasonable prices, correct tax calc).
4. **Phase 4**: Load dashboard, filter recommendations, check charts render correctly, verify portfolio tracking math.

---

## What Makes gept2.0 Different

1. **Short-term predictions** — 5-period ahead price movement and fill probability
2. **Transparent ML** — you own the model, can inspect feature importances and understand why it predicts what it does
3. **Feature-engineered approach** — 50+ carefully designed features covering momentum, volatility, volume, spread, breakouts, and time patterns
4. **Proven architecture** — gradient boosted models (XGBoost/LightGBM) are the gold standard for tabular financial data
5. **Modern web UI** — not locked into RuneLite, accessible from any device
6. **Ground-up pipeline** — every step from data collection to display is yours to control
7. **No GPU required** — trains on CPU in minutes, not hours
