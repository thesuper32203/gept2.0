# gept2.0 — OSRS Grand Exchange Flipping Tool

## Context

Existing OSRS flipping tools have gaps: **Flipping Copilot** hides its logic behind a closed backend (you can't see or customize it), and **GePT** focuses on medium-to-long-term predictions (1h-48h), missing the short-term window (<1h) where active flippers operate. Both lack a transparent, end-to-end pipeline that a solo developer can own and iterate on.

**gept2.0** is a ground-up OSRS GE flipping platform built on a rule-based engine. The pipeline is: **Collect → Analyze → Recommend → Display**. It focuses on two play styles: **short-term active flips (15min-1h)** and **overnight passive flips (8-48h)**. Web dashboard first, Discord bot later.

The rule-based approach was chosen deliberately: it is transparent (every decision is an explicit formula you can read and tune), fast to iterate (no training, no model files, no infrastructure overhead), and proven (simple margin + volume filters are what experienced flippers actually use).

### Developer Context
- Python intermediate (comfortable with syntax, still building class/OOP skills)
- No Docker experience — each phase includes step-by-step setup instructions, not just code
- All code is well-commented and modular so each piece can be understood independently

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Backend API** | Python + FastAPI | Clean async API, easy to learn |
| **Database** | PostgreSQL + TimescaleDB | Time-series optimized, hypertables for price data |
| **Rule Engine** | Pure Python + pandas | Explicit formulas — readable, debuggable, no training required |
| **Task Scheduler** | APScheduler | Lightweight scheduled jobs, no Redis needed |
| **Frontend** | Next.js (React) | Rich dashboard, SSR for fast loads |
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
│Collectors│  Engine  │  API     │  Frontend      │
│(scheduled│ (scanner │ (FastAPI)│  (Next.js)     │
│ polling) │  + rules)│          │                │
├──────────┴──────────┴────┬─────┴────────────────┤
│          PostgreSQL + TimescaleDB               │
│  prices_5min | prices_1hr | items               │
└─────────────────────────────────────────────────┘
```

---

## Phase 0: Environment Setup (Before Any Code)

**Goal:** Get your machine ready to run the project.

### What You Need to Install (one-time)

1. **Docker Desktop** — runs all our services (DB, collectors, API, frontend) in isolated containers
2. **VS Code** — extensions to add: Python, Docker, Pylance
3. **Git** — for version control

### What Docker Does For You

```
Without Docker:               With Docker:
Install Python ✗              docker compose up ✓
Install PostgreSQL ✗          (everything starts automatically)
Configure each to talk ✗
Fight version conflicts ✗
```

### Project Initialization Checklist
- [ ] Install Docker Desktop
- [ ] Create `gept2.0/` folder structure
- [ ] Initialize git repo (`git init`)
- [ ] Create `docker-compose.yml`
- [ ] Create `.env` file (database password, User-Agent — never committed to git)
- [ ] Create `packages/` subfolders
- [ ] Verify Docker is working: `docker compose up db` starts the database

### How You'll Run the Project Day-to-Day

```bash
docker compose up          # Start everything
docker compose up db       # Start just the database
docker compose down        # Stop everything
docker compose logs -f collector  # See logs from a specific service
```

---

## Phase 1: Data Collection (Week 1-2)

**Goal:** Reliable, continuous OSRS GE price data collection and storage.

### Tasks
1. **Initialize project** — monorepo structure, Docker Compose, Poetry setup
2. **Database schema** — TimescaleDB hypertables for multi-resolution price data
3. **OSRS Wiki API collectors** — 2 polling services:
   - `prices_5min` — 5-min OHLC every 300s (primary scanner data)
   - `prices_1hr` — 1-hour averages every 3600s
4. **Item metadata** — fetch and cache item names, buy limits, members status
5. **Backfill script** — pull historical data (last 90 days) for backtesting
6. **Health monitoring** — circuit breaker, retry logic, collection gap detection

### Key Data Source
- OSRS Wiki API: `https://prices.runescape.wiki/api/v1/osrs/`
  - `/5m` — 5-minute OHLC (avg high/low price + volume per item)
  - `/1h` — 1-hour averages
  - `/timeseries?id=<item>&timestep=5m` — historical data for backfill
  - `/mapping` — item metadata (name, buy limit, members, etc.)

### Database Tables
```sql
CREATE TABLE prices_5min (
    time        TIMESTAMPTZ NOT NULL,
    item_id     INT NOT NULL,
    avg_high    BIGINT,
    avg_low     BIGINT,
    high_vol    INT,
    low_vol     INT
);
SELECT create_hypertable('prices_5min', 'time');
-- Same structure for prices_1hr
```

### Project Structure (Phase 1)
```
gept2.0/
├── PRD.md
├── docker-compose.yml
├── docs/
│   ├── phase1/                 # Step-by-step Phase 1 guides
│   └── phase2/                 # Rule-based scanner guide
├── packages/
│   ├── collector/
│   │   ├── collectors/
│   │   │   ├── base.py
│   │   │   ├── prices_5min.py
│   │   │   ├── prices_1hr.py
│   │   │   └── items.py
│   │   ├── db/
│   │   │   ├── schema.sql
│   │   │   └── connection.py
│   │   └── backfill.py
│   └── engine/                 # Phase 2 — rule-based scanner
├── pyproject.toml
└── README.md
```

---

## Phase 2: Rule-Based Flip Scanner (Week 3-4)

**Goal:** A scanner that runs every 5 minutes, reads the latest price snapshot, and surfaces the best flipping opportunities using explicit, tunable rules.

### Why Rule-Based (Not ML)?

Rule-based means every decision is a formula you can read, understand, and tune. There are no model files to train, no data pipelines to maintain, and no black-box outputs to debug.

For OSRS flipping specifically, the signal is already clear: **margin (spread) is profit**. The challenge is filtering out noise — items with unstable spreads, low volume, or margins that disappear after GE tax. Rules handle this directly.

### 2A: Feature Computation

Compute derived signals from raw price snapshots before applying rules.

**File:** `packages/engine/features/builder.py`

#### Base Features

| Feature | Formula | Why it matters |
|---------|---------|----------------|
| `mid_price` | `(avg_high + avg_low) / 2` | Central reference price |
| `spread` | `avg_high - avg_low` | The raw flip margin (gross profit per unit) |
| `volume_total` | `high_vol + low_vol` | Total trading activity — proxy for liquidity |
| `spread_pct` | `spread / mid_price` | Normalized margin — comparable across different-priced items |
| `volume_imbalance` | `(high_vol - low_vol) / volume_total` | Buy/sell pressure — imbalance signals demand shifts |

#### Lag Features (Recent History)

Always `groupby("item_id")` before shifting — without this, item A's price bleeds into item B's lag:

```python
df["price_lag1"] = df.groupby("item_id")["mid_price"].shift(1)
df["return_1"] = (df["mid_price"] - df["price_lag1"]) / df["price_lag1"]
```

Compute lags at t-1, t-5, t-10, t-20 for price; t-1, t-5 for volume and spread.

#### Rolling Features (Trend & Volatility)

```python
df["ma_20"] = df.groupby("item_id")["mid_price"].transform(
    lambda x: x.rolling(20).mean()
)
```

Key rolling signals:
- `ma_5`, `ma_20` — short and medium-term moving averages
- `spread_cv` — coefficient of variation of spread (`spread_std / spread_mean`) — measures spread stability
- `volume_ma20` — baseline volume level

### 2B: Rule-Based Scanner

**File:** `packages/engine/flipper/scanner.py`

The scanner applies a series of explicit filters to the latest price snapshot, then ranks survivors by margin.

#### Constants (all tunable)

```python
MIN_VOLUME = 100            # Items trading fewer than this per 5min are illiquid
HIGH_VOLUME_THRESHOLD = 5000  # High-volume items get stricter margin requirements
MAX_SPREAD_CV = 0.80        # Reject items where spread bounces around too much
MIN_MARGIN_PCT = 0.01       # Minimum 1% net margin after tax (high-vol items)
GE_TAX = 0.02               # 2% tax on the sell side, capped at 5M GP
TOP_N = 20                  # Show top N results
```

#### Filter Pipeline

**Step 1 — Volume filter:** Drop items with insufficient trading activity.
```
volume_total >= MIN_VOLUME
```
Items with low volume are risky — your offer might sit for hours.

**Step 2 — Stability filter:** Drop items where the spread jumps around unpredictably.
```
spread_cv <= MAX_SPREAD_CV
```
A high coefficient of variation means the margin you see now may not be there when your buy order fills.

**Step 3 — Margin calculation:** Compute real profit after GE tax.
```
tax = floor(avg_high * GE_TAX)        # Tax is on the sell price
profit_per_unit = spread - tax
margin_pct = profit_per_unit / avg_high
```

**Step 4 — Margin filter:** Require minimum net margin.
- High-volume items (>= HIGH_VOLUME_THRESHOLD): require `MIN_MARGIN_PCT` (stricter — high competition)
- Low-volume items: require `MIN_MARGIN_PCT / 2` (looser — less competition)

**Step 5 — Rank and return top N** sorted by `margin_pct` descending.

#### Output per item

| Field | Description |
|-------|-------------|
| `item_id` | Item identifier |
| `recommended_bid` | `avg_low - 1` (undercut current buy orders) |
| `recommended_ask` | `avg_high + 1` (overprice current sell orders) |
| `profit_per_unit` | GP per unit after tax |
| `margin_pct` | Net margin as a percentage |
| `volume_total` | How actively this item trades |
| `spread_cv` | How stable the spread is (lower = more reliable) |

### 2C: Backtester

**File:** `packages/engine/flipper/backtester.py`

Validates the scanner against historical data before trusting it with real GP.

#### Simulation Logic

For each 5-minute snapshot in historical data:
1. Run the scanner to find flip candidates
2. For each candidate, simulate buying at `recommended_bid` (up to buy limit)
3. Simulate selling at `recommended_ask` in a future snapshot
4. Track capital, profit, and open positions

#### Key Constraints

| Constraint | Why |
|-----------|-----|
| GE buy limit | Each item has a buy limit per 4 hours — must be respected |
| 4-hour cooldown | After hitting buy limit, cannot buy again until cooldown expires |
| Capital tracking | Cannot buy more than available GP |
| Tax on every sell | 2% tax deducted from every sale, capped at 5M GP |

#### Metrics to Track

- Total profit (GP)
- Number of completed flips
- Win rate (% of flips that were profitable)
- Maximum drawdown (worst losing streak in capital terms)
- Average time to fill (how long positions stayed open)

### 2D: Running the Engine

```bash
# Run scanner once (see current recommendations)
python -m packages.engine.main --mode scan

# Run backtest over historical data
python -m packages.engine.main --mode backtest --days 14
```

---

## Phase 3: API (Week 5-6)

**Goal:** Serve scanner results via a FastAPI backend.

### Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/recommendations` | Top flip recommendations from the latest scan |
| `GET /api/items` | Searchable item list |
| `GET /api/history/{item_id}` | Price history for an item |
| `GET /api/portfolio` | Tracked flips and P&L |

### Recommendation Scoring

Each recommendation includes:
- **Profit calc**: `profit = (sell - buy) * qty - tax`
- **ROI**: `roi = profit / capital_required`
- **Capital required**: `recommended_bid * buy_limit`

### User Constraint Filtering

- Available capital (GP budget)
- Play style: Active (<1h flips), Passive (8-48h)
- Item blacklist/whitelist

---

## Phase 4: Web Dashboard (Week 6-8)

**Goal:** User-facing dashboard to view recommendations and track performance.

### Pages

1. **Dashboard** — top flip recommendations with filter controls
   - Card per item: buy/sell price, profit per unit, margin %, volume
   - Filter by capital, item type, play style
2. **Item detail** — price chart, spread history, volume bars
3. **Portfolio tracker** — log flips, track P&L, running win rate

### Tech
- Next.js App Router
- Recharts for price visualization
- TanStack Query for data fetching
- Tailwind CSS

---

## Phase 5: Discord Bot (Week 8+)

**Goal:** Deliver recommendations via Discord.

### Commands
- `/flips` — top recommendations with capital filter
- `/track <item>` — watch an item for price alerts
- `/portfolio` — your tracked flips and P&L

---

## Verification Plan

1. **Phase 1**: Query DB — confirm prices collecting continuously, no gaps, matches Wiki API directly.
2. **Phase 2**: Run backtest — confirm positive GP over 14 days, verify no tax/cooldown accounting bugs, review top 20 recommendations manually for sanity.
3. **Phase 3**: Hit API endpoints — verify recommendations match scanner output, capital filtering works.
4. **Phase 4**: Load dashboard — filter recommendations, check charts render, verify portfolio math.

---

## What Makes gept2.0 Different

1. **Transparent logic** — every filter and formula is readable code you control
2. **Correct economics** — GE tax, buy limits, and cooldowns all modeled accurately
3. **Backtested** — validated against real historical data before trusting with GP
4. **Modern web UI** — accessible from any device, not locked into RuneLite
5. **Ground-up pipeline** — every step from data collection to display is yours to own and extend
