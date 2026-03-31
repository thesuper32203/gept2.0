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
| **ML Framework** | PyTorch | PatchTST-style transformers, good solo-dev ergonomics |
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
│Collectors│  ML      │  API     │  Frontend      │
│(scheduled│  Worker  │ (FastAPI)│  (Next.js)     │
│ polling) │(training │          │                │
│          │+inference│          │                │
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
│   │   ├── features/           # Feature computation
│   │   ├── model/              # PatchTST transformer
│   │   ├── training/           # Training pipeline
│   │   ├── inference/          # Prediction service
│   │   └── recommendations/    # Scoring + filtering
│   ├── api/                    # Phase 3 — FastAPI backend
│   ├── web/                    # Phase 4 — Next.js dashboard
│   └── bot/                    # Phase 5 — Discord bot
├── pyproject.toml
└── README.md
```

---

## Phase 2: Feature Engineering & ML Model (Week 3-5)

**Goal:** Train a multi-horizon price prediction model. Every step documented so you understand what the model does and why.

### 2A: Feature Engine (Week 3)
Compute features from raw price data. Each feature has a clear purpose:

| Feature | What it is | Why it matters for flipping |
|---------|-----------|---------------------------|
| Moving averages (30min, 1hr, 4hr, 12hr, 1d, 1w) | Average price over a rolling window | Shows trend direction — is price rising or falling? |
| Price returns (% change) | How much price changed over a window | Captures momentum — fast rises often correct |
| Volatility (rolling std dev) | How much price bounces around | High volatility = more flip opportunity but more risk |
| Volume ratios (buy/sell imbalance) | Ratio of instant-buy vs instant-sell volume | Imbalance signals demand shifts |
| Spread (high - low as % of price) | Gap between buy and sell price | The fundamental flip margin |
| Time-of-day / day-of-week | Cyclical time encoding | Prices follow player activity patterns |

### 2B: ML Model — Multi-Resolution Transformer (Week 4-5)
**What is this?** A neural network (think: pattern recognition engine) that looks at price history at multiple zoom levels and predicts where prices are heading.

**Why a transformer?** Transformers excel at finding patterns in sequences (like price over time). GePT proved this works for OSRS data.

**Architecture (inspired by GePT's PatchTST, adjusted for available API data):**
- **Short encoder**: 5-min data, 24h lookback → predict **30min, 1h, 2h, 4h** (active flips)
- **Long encoder**: 1-hr data, 14d lookback → predict **12h, 24h, 48h** (overnight flips)
- **Fusion head**: combines both encoders → unified prediction
- **Output**: Price quantiles (p10, p25, p50, p75, p90) per horizon

> **What are quantiles?** Instead of predicting "the price will be 1000gp", the model says "there's a 10% chance it'll be below 950, 50% chance below 1000, 90% chance below 1050." This range tells you how confident the model is.

### 2C: Training & Evaluation
- **Training pipeline** — data loading, time-based train/val/test split, training loop
- **Evaluation metrics** — calibration (are the quantiles accurate?), directional accuracy (does it predict up/down correctly >55% of the time?), profit backtesting (would following the model make money?)
- **Inference service** — runs every 5 minutes, stores predictions in DB

### Key Improvements Over GePT
- **Two-mode focus** — active flipping (30min-4h) AND overnight (12-48h), not trying to cover everything
- **5-min as primary short-term signal** — matches available API resolution, same as GePT but focused on shorter prediction horizons
- **Directional confidence** — probability of price moving up/down, not just quantiles

### Companion Doc: `docs/ml-explained.md`
Will contain: what is a transformer, how PatchTST works, what quantile regression means, how to interpret model output — all in plain language with OSRS examples

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
- Fill probability concept
- Confidence tiers (High/Medium/Low)

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
2. **Phase 2**: Run model evaluation — check calibration (predicted p50 should be median), directional accuracy >55%, backtest profit > baseline (buy-low-sell-high without ML).
3. **Phase 3**: Hit API endpoints, verify recommendations make sense (positive EV, reasonable prices, correct tax calc).
4. **Phase 4**: Load dashboard, filter recommendations, check charts render correctly, verify portfolio tracking math.

---

## What Makes gept2.0 Different

1. **Short-term predictions** — 30min/1h/2h horizons that existing tools miss
2. **Transparent ML** — you own the model, can inspect and improve it
3. **Multi-resolution fusion** — combines rapid price movements with longer trends
4. **Modern web UI** — not locked into RuneLite, accessible from any device
5. **Ground-up pipeline** — every step from data collection to display is yours to control
