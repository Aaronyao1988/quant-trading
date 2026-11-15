# V1–V4 90-Day BTC/USDT Regime Benchmark

**Generated (UTC):** 2026-11-15T10:28:30.049506+00:00
**Cache end:** 2026-11-15T10:27:22.346000+00:00
**Bars:** 8642 × 15m trading window (~90d); 134 × 1d (warmup included in cache).
**Initial capital:** $200.00 · **Allocation:** 50% per entry
**Fees:** spot 0.10%/side · swap 0.05%/side
**Stop policy:** OHLC touch at 2% vs entry; fill at stop price
**Funding (V4):** historical OKX funding-rate series (276 snapshots).

## Core comparison

| Variant | Trades | Long WR | Short WR | Fees | Funding | Max DD | Final NAV | Total return |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| V1 | 176 | 30.68% | n/a | $34.8397 | $0.0000 | -22.20% | $172.20 | -13.90% |
| V2 | 128 | 57.81% | n/a | $24.4301 | $0.0000 | -11.27% | $178.55 | -10.72% |
| V3 | 68 | 52.94% | n/a | $13.1779 | $0.0000 | -6.42% | $187.88 | -6.06% |
| V4 | 172 | 30.19% | 30.30% | $16.4980 | $0.0740 | -14.12% | $198.13 | -0.94% |

## Strategy notes

- **V1:** SMA(10)/SMA(30) golden/death, spot, 0.10%/side.
- **V2:** ADX(14)>25 → SMA trend; ADX<20 → Z(20) MR (entry Z<-2, exit Z≥0); [20,25] no new entries. Exits always follow `entry_strategy` (orphan policy).
- **V3:** V2 + new longs only if close > prior-day daily SMA30; exits unrestricted.
- **V4:** 1x BTC-USDT-SWAP; long regime above daily SMA30 / short below; 15m golden/death; contract step 0.01 (=0.01 BTC); 2% H/L stop.

## Per-variant detail

### V1

- Instrument: `spot`
- Round-trip trades: **176** (long 176, short 0)
- Overall win rate: 30.68%
- Cumulative fees: $34.8397
- Cumulative funding paid(+)/received pattern: $0.0000
- Max drawdown: -22.20%
- Final NAV: $172.20 (-13.90%)

Regime breakdown (contiguous ADX runs on 15m, aggregated):

| Regime | Bars | Runs | Sum segment return | Avg segment return |
|---|---:|---:|---:|---:|
| deadband_20_25 | 1478 | 265 | -6.59% | -0.02% |
| trend_adx_gt_25 | 3988 | 138 | 5.92% | 0.04% |
| mr_adx_lt_20 | 3175 | 126 | -12.46% | -0.10% |

Trades (n=176):

| # | Side | Entry strategy | Return | Exit reason |
|---:|---|---|---:|---|
| 1 | long | sma | +0.77% | sma_death |
| 2 | long | sma | -0.23% | sma_death |
| 3 | long | sma | -0.05% | sma_death |
| 4 | long | sma | -0.63% | sma_death |
| 5 | long | sma | +7.46% | sma_death |
| 6 | long | sma | +11.43% | sma_death |
| 7 | long | sma | -0.58% | sma_death |
| 8 | long | sma | -0.64% | sma_death |
| 9 | long | sma | -0.35% | sma_death |
| 10 | long | sma | -0.31% | sma_death |
| 11 | long | sma | -0.44% | sma_death |
| 12 | long | sma | +0.64% | sma_death |
| 13 | long | sma | +1.72% | sma_death |
| 14 | long | sma | +0.94% | sma_death |
| 15 | long | sma | -0.47% | sma_death |
| 16 | long | sma | -0.32% | sma_death |
| 17 | long | sma | +0.61% | sma_death |
| 18 | long | sma | +0.20% | sma_death |
| 19 | long | sma | -0.89% | sma_death |
| 20 | long | sma | -0.56% | sma_death |
| 21 | long | sma | -0.30% | sma_death |
| 22 | long | sma | +0.51% | sma_death |
| 23 | long | sma | -0.38% | sma_death |
| 24 | long | sma | -0.25% | sma_death |
| 25 | long | sma | +0.08% | sma_death |
| 26 | long | sma | -0.09% | sma_death |
| 27 | long | sma | -1.13% | sma_death |
| 28 | long | sma | -0.93% | sma_death |
| 29 | long | sma | -0.41% | sma_death |
| 30 | long | sma | -0.91% | sma_death |
| 31 | long | sma | -0.28% | sma_death |
| 32 | long | sma | +0.33% | sma_death |
| 33 | long | sma | +4.07% | sma_death |
| 34 | long | sma | -0.25% | sma_death |
| 35 | long | sma | -2.00% | hard_stop_2pct |
| 36 | long | sma | -0.04% | sma_death |
| 37 | long | sma | -0.04% | sma_death |
| 38 | long | sma | -0.09% | sma_death |
| 39 | long | sma | -0.01% | sma_death |
| 40 | long | sma | -0.12% | sma_death |
| 41 | long | sma | -0.33% | sma_death |
| 42 | long | sma | -0.09% | sma_death |
| 43 | long | sma | -0.73% | sma_death |
| 44 | long | sma | -0.26% | sma_death |
| 45 | long | sma | -0.52% | sma_death |
| 46 | long | sma | -0.37% | sma_death |
| 47 | long | sma | -0.21% | sma_death |
| 48 | long | sma | +0.22% | sma_death |
| 49 | long | sma | -1.31% | sma_death |
| 50 | long | sma | -0.34% | sma_death |
| 51 | long | sma | -0.44% | sma_death |
| 52 | long | sma | -0.23% | sma_death |
| 53 | long | sma | -0.56% | sma_death |
| 54 | long | sma | -0.14% | sma_death |
| 55 | long | sma | +0.04% | sma_death |
| 56 | long | sma | -0.27% | sma_death |
| 57 | long | sma | -0.04% | sma_death |
| 58 | long | sma | -0.23% | sma_death |
| 59 | long | sma | -0.44% | sma_death |
| 60 | long | sma | +1.24% | sma_death |
| 61 | long | sma | -0.70% | sma_death |
| 62 | long | sma | -0.20% | sma_death |
| 63 | long | sma | +0.29% | sma_death |
| 64 | long | sma | -0.34% | sma_death |
| 65 | long | sma | +5.60% | sma_death |
| 66 | long | sma | +0.11% | sma_death |
| 67 | long | sma | -0.26% | sma_death |
| 68 | long | sma | -0.11% | sma_death |
| 69 | long | sma | +0.55% | sma_death |
| 70 | long | sma | +5.17% | sma_death |
| 71 | long | sma | +0.04% | sma_death |
| 72 | long | sma | -0.34% | sma_death |
| 73 | long | sma | -0.17% | sma_death |
| 74 | long | sma | -1.12% | sma_death |
| 75 | long | sma | -0.11% | sma_death |
| 76 | long | sma | -0.43% | sma_death |
| 77 | long | sma | -1.03% | sma_death |
| 78 | long | sma | +0.06% | sma_death |
| 79 | long | sma | -0.10% | sma_death |
| 80 | long | sma | -0.17% | sma_death |
| 81 | long | sma | -0.16% | sma_death |
| 82 | long | sma | +0.21% | sma_death |
| 83 | long | sma | -0.65% | sma_death |
| 84 | long | sma | +0.24% | sma_death |
| 85 | long | sma | -0.55% | sma_death |
| 86 | long | sma | -0.23% | sma_death |
| 87 | long | sma | +0.78% | sma_death |
| 88 | long | sma | -0.51% | sma_death |
| 89 | long | sma | +0.90% | sma_death |
| 90 | long | sma | +0.89% | sma_death |
| 91 | long | sma | +0.15% | sma_death |
| 92 | long | sma | -0.01% | sma_death |
| 93 | long | sma | -0.08% | sma_death |
| 94 | long | sma | +0.03% | sma_death |
| 95 | long | sma | +0.13% | sma_death |
| 96 | long | sma | +0.34% | sma_death |
| 97 | long | sma | +0.55% | sma_death |
| 98 | long | sma | -0.42% | sma_death |
| 99 | long | sma | -0.59% | sma_death |
| 100 | long | sma | -0.38% | sma_death |
| 101 | long | sma | -0.35% | sma_death |
| 102 | long | sma | -0.05% | sma_death |
| 103 | long | sma | -0.19% | sma_death |
| 104 | long | sma | -0.31% | sma_death |
| 105 | long | sma | +0.98% | sma_death |
| 106 | long | sma | +0.52% | sma_death |
| 107 | long | sma | -0.05% | sma_death |
| 108 | long | sma | -0.09% | sma_death |
| 109 | long | sma | +0.45% | sma_death |
| 110 | long | sma | -0.48% | sma_death |
| 111 | long | sma | -1.28% | sma_death |
| 112 | long | sma | +0.49% | sma_death |
| 113 | long | sma | -0.14% | sma_death |
| 114 | long | sma | -0.06% | sma_death |
| 115 | long | sma | -0.45% | sma_death |
| 116 | long | sma | -0.46% | sma_death |
| 117 | long | sma | -0.41% | sma_death |
| 118 | long | sma | +0.21% | sma_death |
| 119 | long | sma | -0.33% | sma_death |
| 120 | long | sma | +0.22% | sma_death |
| 121 | long | sma | -0.33% | sma_death |
| 122 | long | sma | -0.23% | sma_death |
| 123 | long | sma | -0.04% | sma_death |
| 124 | long | sma | -0.38% | sma_death |
| 125 | long | sma | -0.20% | sma_death |
| 126 | long | sma | -0.79% | sma_death |
| 127 | long | sma | +1.03% | sma_death |
| 128 | long | sma | -0.59% | sma_death |
| 129 | long | sma | -0.61% | sma_death |
| 130 | long | sma | +0.70% | sma_death |
| 131 | long | sma | -0.07% | sma_death |
| 132 | long | sma | +1.32% | sma_death |
| 133 | long | sma | -0.30% | sma_death |
| 134 | long | sma | +0.02% | sma_death |
| 135 | long | sma | -0.66% | sma_death |
| 136 | long | sma | -0.29% | sma_death |
| 137 | long | sma | -0.56% | sma_death |
| 138 | long | sma | +0.16% | sma_death |
| 139 | long | sma | -0.24% | sma_death |
| 140 | long | sma | -0.71% | sma_death |
| 141 | long | sma | +0.04% | sma_death |
| 142 | long | sma | -0.04% | sma_death |
| 143 | long | sma | -0.59% | sma_death |
| 144 | long | sma | +1.39% | sma_death |
| 145 | long | sma | -0.42% | sma_death |
| 146 | long | sma | -0.13% | sma_death |
| 147 | long | sma | +0.83% | sma_death |
| 148 | long | sma | -1.04% | sma_death |
| 149 | long | sma | -0.30% | sma_death |
| 150 | long | sma | -0.10% | sma_death |
| 151 | long | sma | +0.20% | sma_death |
| 152 | long | sma | +0.22% | sma_death |
| 153 | long | sma | -0.44% | sma_death |
| 154 | long | sma | -0.22% | sma_death |
| 155 | long | sma | -0.40% | sma_death |
| 156 | long | sma | +0.19% | sma_death |
| 157 | long | sma | +0.80% | sma_death |
| 158 | long | sma | +0.93% | sma_death |
| 159 | long | sma | -0.25% | sma_death |
| 160 | long | sma | -0.44% | sma_death |
| 161 | long | sma | -0.57% | sma_death |
| 162 | long | sma | +0.07% | sma_death |
| 163 | long | sma | -0.03% | sma_death |
| 164 | long | sma | -0.23% | sma_death |
| 165 | long | sma | -0.27% | sma_death |
| 166 | long | sma | -0.69% | sma_death |
| 167 | long | sma | +0.09% | sma_death |
| 168 | long | sma | -0.21% | sma_death |
| 169 | long | sma | -0.46% | sma_death |
| 170 | long | sma | +0.38% | sma_death |
| 171 | long | sma | -0.69% | sma_death |
| 172 | long | sma | -0.99% | sma_death |
| 173 | long | sma | -1.56% | sma_death |
| 174 | long | sma | -1.27% | sma_death |
| 175 | long | sma | -0.36% | sma_death |
| 176 | long | sma | -1.42% | sma_death |

### V2

- Instrument: `spot`
- Round-trip trades: **128** (long 128, short 0)
- Overall win rate: 57.81%
- Cumulative fees: $24.4301
- Cumulative funding paid(+)/received pattern: $0.0000
- Max drawdown: -11.27%
- Final NAV: $178.55 (-10.72%)

Regime breakdown (contiguous ADX runs on 15m, aggregated):

| Regime | Bars | Runs | Sum segment return | Avg segment return |
|---|---:|---:|---:|---:|
| deadband_20_25 | 1478 | 265 | -0.58% | -0.00% |
| trend_adx_gt_25 | 3988 | 138 | -4.14% | -0.03% |
| mr_adx_lt_20 | 3175 | 126 | -4.33% | -0.03% |

Trades (n=128):

| # | Side | Entry strategy | Return | Exit reason |
|---:|---|---|---:|---|
| 1 | long | sma | +0.77% | sma_death |
| 2 | long | zscore | +0.30% | z_exit_ge_0 |
| 3 | long | zscore | -0.23% | z_exit_ge_0 |
| 4 | long | sma | -0.35% | sma_death |
| 5 | long | zscore | -0.01% | z_safety_death |
| 6 | long | sma | +0.64% | sma_death |
| 7 | long | zscore | +0.73% | z_exit_ge_0 |
| 8 | long | zscore | +0.04% | z_safety_death |
| 9 | long | zscore | -0.00% | z_exit_ge_0 |
| 10 | long | zscore | +0.26% | z_exit_ge_0 |
| 11 | long | zscore | +0.23% | z_exit_ge_0 |
| 12 | long | sma | -0.30% | sma_death |
| 13 | long | zscore | +0.23% | z_exit_ge_0 |
| 14 | long | zscore | +0.19% | z_exit_ge_0 |
| 15 | long | sma | +0.08% | sma_death |
| 16 | long | sma | -0.93% | sma_death |
| 17 | long | sma | -0.41% | sma_death |
| 18 | long | zscore | -0.51% | z_safety_death |
| 19 | long | zscore | +0.04% | z_exit_ge_0 |
| 20 | long | sma | -0.28% | sma_death |
| 21 | long | zscore | +0.40% | z_exit_ge_0 |
| 22 | long | sma | -0.25% | sma_death |
| 23 | long | zscore | +0.41% | z_exit_ge_0 |
| 24 | long | zscore | -0.28% | z_safety_death |
| 25 | long | sma | -0.04% | sma_death |
| 26 | long | zscore | +0.12% | z_exit_ge_0 |
| 27 | long | zscore | +0.33% | z_exit_ge_0 |
| 28 | long | zscore | -0.05% | z_safety_death |
| 29 | long | zscore | +0.09% | z_exit_ge_0 |
| 30 | long | sma | -0.09% | sma_death |
| 31 | long | zscore | +0.17% | z_exit_ge_0 |
| 32 | long | zscore | +0.39% | z_safety_death |
| 33 | long | sma | -0.37% | sma_death |
| 34 | long | zscore | -0.31% | z_exit_ge_0 |
| 35 | long | zscore | +0.11% | z_safety_death |
| 36 | long | sma | -0.44% | sma_death |
| 37 | long | sma | -0.23% | sma_death |
| 38 | long | sma | -0.14% | sma_death |
| 39 | long | zscore | -0.03% | z_safety_death |
| 40 | long | zscore | +0.05% | z_exit_ge_0 |
| 41 | long | zscore | +0.03% | z_safety_death |
| 42 | long | zscore | -0.36% | z_exit_ge_0 |
| 43 | long | sma | -0.44% | sma_death |
| 44 | long | sma | +1.24% | sma_death |
| 45 | long | zscore | -0.12% | z_safety_death |
| 46 | long | zscore | +0.34% | z_safety_death |
| 47 | long | zscore | +0.42% | z_exit_ge_0 |
| 48 | long | zscore | +0.38% | z_exit_ge_0 |
| 49 | long | zscore | +0.30% | z_exit_ge_0 |
| 50 | long | sma | +0.04% | sma_death |
| 51 | long | zscore | +0.40% | z_exit_ge_0 |
| 52 | long | sma | -0.17% | sma_death |
| 53 | long | sma | -0.11% | sma_death |
| 54 | long | zscore | +0.71% | z_exit_ge_0 |
| 55 | long | zscore | -0.00% | z_safety_death |
| 56 | long | zscore | +0.27% | z_exit_ge_0 |
| 57 | long | zscore | -0.17% | z_safety_death |
| 58 | long | zscore | +0.71% | z_exit_ge_0 |
| 59 | long | zscore | -1.20% | z_exit_ge_0 |
| 60 | long | sma | +0.24% | sma_death |
| 61 | long | zscore | +0.03% | z_exit_ge_0 |
| 62 | long | zscore | +0.21% | z_exit_ge_0 |
| 63 | long | zscore | +0.21% | z_exit_ge_0 |
| 64 | long | zscore | +0.24% | z_exit_ge_0 |
| 65 | long | sma | +0.15% | sma_death |
| 66 | long | sma | +0.55% | sma_death |
| 67 | long | sma | -0.42% | sma_death |
| 68 | long | zscore | -0.03% | z_exit_ge_0 |
| 69 | long | zscore | +0.43% | z_exit_ge_0 |
| 70 | long | sma | -0.05% | sma_death |
| 71 | long | sma | -0.19% | sma_death |
| 72 | long | zscore | +0.18% | z_exit_ge_0 |
| 73 | long | zscore | +0.16% | z_exit_ge_0 |
| 74 | long | sma | +0.98% | sma_death |
| 75 | long | sma | -1.28% | sma_death |
| 76 | long | sma | +0.49% | sma_death |
| 77 | long | zscore | -1.26% | z_exit_ge_0 |
| 78 | long | sma | -0.46% | sma_death |
| 79 | long | zscore | +0.65% | z_exit_ge_0 |
| 80 | long | zscore | +0.50% | z_exit_ge_0 |
| 81 | long | zscore | +0.37% | z_exit_ge_0 |
| 82 | long | zscore | +0.02% | z_exit_ge_0 |
| 83 | long | zscore | +0.20% | z_exit_ge_0 |
| 84 | long | zscore | +0.03% | z_safety_death |
| 85 | long | zscore | +0.19% | z_exit_ge_0 |
| 86 | long | sma | +1.03% | sma_death |
| 87 | long | zscore | -0.26% | z_safety_death |
| 88 | long | zscore | +0.27% | z_exit_ge_0 |
| 89 | long | zscore | +0.23% | z_exit_ge_0 |
| 90 | long | zscore | +0.05% | z_safety_death |
| 91 | long | sma | -0.30% | sma_death |
| 92 | long | zscore | +0.32% | z_exit_ge_0 |
| 93 | long | zscore | +0.46% | z_exit_ge_0 |
| 94 | long | sma | +0.16% | sma_death |
| 95 | long | zscore | -0.18% | z_exit_ge_0 |
| 96 | long | zscore | -0.32% | z_safety_death |
| 97 | long | zscore | +0.12% | z_safety_death |
| 98 | long | zscore | +0.51% | z_exit_ge_0 |
| 99 | long | sma | -0.13% | sma_death |
| 100 | long | zscore | +0.43% | z_exit_ge_0 |
| 101 | long | sma | -1.04% | sma_death |
| 102 | long | zscore | -0.21% | z_safety_death |
| 103 | long | sma | -0.22% | sma_death |
| 104 | long | zscore | +0.39% | z_exit_ge_0 |
| 105 | long | zscore | -0.74% | z_exit_ge_0 |
| 106 | long | sma | +0.80% | sma_death |
| 107 | long | sma | +0.93% | sma_death |
| 108 | long | sma | -0.25% | sma_death |
| 109 | long | zscore | -2.00% | hard_stop_2pct |
| 110 | long | sma | -0.44% | sma_death |
| 111 | long | sma | -0.57% | sma_death |
| 112 | long | zscore | +0.60% | z_exit_ge_0 |
| 113 | long | zscore | +0.15% | z_safety_death |
| 114 | long | zscore | +0.02% | z_exit_ge_0 |
| 115 | long | sma | -0.23% | sma_death |
| 116 | long | zscore | -0.12% | z_safety_death |
| 117 | long | zscore | +0.05% | z_safety_death |
| 118 | long | zscore | +0.18% | z_exit_ge_0 |
| 119 | long | zscore | +0.10% | z_exit_ge_0 |
| 120 | long | zscore | +0.51% | z_exit_ge_0 |
| 121 | long | zscore | +0.51% | z_exit_ge_0 |
| 122 | long | zscore | +0.54% | z_exit_ge_0 |
| 123 | long | zscore | +0.32% | z_exit_ge_0 |
| 124 | long | sma | -1.56% | sma_death |
| 125 | long | zscore | -0.44% | z_safety_death |
| 126 | long | zscore | +0.35% | z_exit_ge_0 |
| 127 | long | sma | -0.36% | sma_death |
| 128 | long | sma | -1.42% | sma_death |

### V3

- Instrument: `spot`
- Round-trip trades: **68** (long 68, short 0)
- Overall win rate: 52.94%
- Cumulative fees: $13.1779
- Cumulative funding paid(+)/received pattern: $0.0000
- Max drawdown: -6.42%
- Final NAV: $187.88 (-6.06%)

Regime breakdown (contiguous ADX runs on 15m, aggregated):

| Regime | Bars | Runs | Sum segment return | Avg segment return |
|---|---:|---:|---:|---:|
| deadband_20_25 | 1478 | 265 | -0.47% | -0.00% |
| trend_adx_gt_25 | 3988 | 138 | -2.63% | -0.02% |
| mr_adx_lt_20 | 3175 | 126 | -2.09% | -0.02% |

Trades (n=68):

| # | Side | Entry strategy | Return | Exit reason |
|---:|---|---|---:|---|
| 1 | long | zscore | -0.23% | z_exit_ge_0 |
| 2 | long | sma | -0.35% | sma_death |
| 3 | long | zscore | -0.01% | z_safety_death |
| 4 | long | sma | +0.64% | sma_death |
| 5 | long | zscore | +0.73% | z_exit_ge_0 |
| 6 | long | zscore | +0.04% | z_safety_death |
| 7 | long | zscore | -0.00% | z_exit_ge_0 |
| 8 | long | zscore | +0.26% | z_exit_ge_0 |
| 9 | long | zscore | +0.23% | z_exit_ge_0 |
| 10 | long | sma | -0.30% | sma_death |
| 11 | long | zscore | +0.23% | z_exit_ge_0 |
| 12 | long | zscore | +0.19% | z_exit_ge_0 |
| 13 | long | sma | +0.08% | sma_death |
| 14 | long | sma | -0.93% | sma_death |
| 15 | long | sma | -0.41% | sma_death |
| 16 | long | zscore | -0.51% | z_safety_death |
| 17 | long | zscore | +0.04% | z_exit_ge_0 |
| 18 | long | sma | -0.28% | sma_death |
| 19 | long | zscore | +0.40% | z_exit_ge_0 |
| 20 | long | sma | -0.25% | sma_death |
| 21 | long | zscore | +0.41% | z_exit_ge_0 |
| 22 | long | zscore | -0.28% | z_safety_death |
| 23 | long | sma | -0.04% | sma_death |
| 24 | long | zscore | +0.12% | z_exit_ge_0 |
| 25 | long | zscore | +0.33% | z_exit_ge_0 |
| 26 | long | zscore | -0.05% | z_safety_death |
| 27 | long | zscore | +0.09% | z_exit_ge_0 |
| 28 | long | sma | -0.09% | sma_death |
| 29 | long | zscore | +0.17% | z_exit_ge_0 |
| 30 | long | zscore | +0.39% | z_safety_death |
| 31 | long | sma | -0.37% | sma_death |
| 32 | long | zscore | -0.31% | z_exit_ge_0 |
| 33 | long | zscore | +0.11% | z_safety_death |
| 34 | long | sma | -0.44% | sma_death |
| 35 | long | sma | -0.23% | sma_death |
| 36 | long | sma | -0.14% | sma_death |
| 37 | long | zscore | -0.03% | z_safety_death |
| 38 | long | zscore | +0.05% | z_exit_ge_0 |
| 39 | long | zscore | +0.03% | z_safety_death |
| 40 | long | zscore | -0.36% | z_exit_ge_0 |
| 41 | long | sma | -0.44% | sma_death |
| 42 | long | sma | +1.24% | sma_death |
| 43 | long | sma | +0.04% | sma_death |
| 44 | long | zscore | +0.40% | z_exit_ge_0 |
| 45 | long | sma | -0.17% | sma_death |
| 46 | long | sma | -0.11% | sma_death |
| 47 | long | zscore | +0.71% | z_exit_ge_0 |
| 48 | long | zscore | -0.00% | z_safety_death |
| 49 | long | zscore | +0.27% | z_exit_ge_0 |
| 50 | long | zscore | -0.17% | z_safety_death |
| 51 | long | zscore | +0.71% | z_exit_ge_0 |
| 52 | long | zscore | -1.20% | z_exit_ge_0 |
| 53 | long | sma | +0.24% | sma_death |
| 54 | long | zscore | +0.03% | z_exit_ge_0 |
| 55 | long | zscore | +0.21% | z_exit_ge_0 |
| 56 | long | zscore | +0.21% | z_exit_ge_0 |
| 57 | long | zscore | +0.24% | z_exit_ge_0 |
| 58 | long | sma | +0.15% | sma_death |
| 59 | long | sma | +0.55% | sma_death |
| 60 | long | sma | -0.42% | sma_death |
| 61 | long | zscore | -0.03% | z_exit_ge_0 |
| 62 | long | zscore | +0.43% | z_exit_ge_0 |
| 63 | long | sma | -0.05% | sma_death |
| 64 | long | sma | -0.19% | sma_death |
| 65 | long | zscore | +0.18% | z_exit_ge_0 |
| 66 | long | zscore | +0.16% | z_exit_ge_0 |
| 67 | long | sma | -1.28% | sma_death |
| 68 | long | sma | +0.49% | sma_death |

### V4

- Instrument: `swap`
- Round-trip trades: **172** (long 106, short 66)
- Overall win rate: 30.23%
- Cumulative fees: $16.4980
- Cumulative funding paid(+)/received pattern: $0.0740
- Max drawdown: -14.12%
- Final NAV: $198.13 (-0.94%)

Regime breakdown (contiguous ADX runs on 15m, aggregated):

| Regime | Bars | Runs | Sum segment return | Avg segment return |
|---|---:|---:|---:|---:|
| deadband_20_25 | 1478 | 265 | -3.67% | -0.01% |
| trend_adx_gt_25 | 3988 | 138 | 9.34% | 0.07% |
| mr_adx_lt_20 | 3175 | 126 | -6.50% | -0.05% |

Trades (n=172):

| # | Side | Entry strategy | Return | Exit reason |
|---:|---|---|---:|---|
| 1 | short | macro | -0.22% | golden_exit_short |
| 2 | short | macro | -0.20% | golden_exit_short |
| 3 | long | macro | -0.63% | death_exit_long |
| 4 | long | macro | +7.46% | death_exit_long |
| 5 | long | macro | +11.43% | death_exit_long |
| 6 | long | macro | -0.58% | death_exit_long |
| 7 | long | macro | -0.64% | death_exit_long |
| 8 | long | macro | -0.35% | death_exit_long |
| 9 | long | macro | -0.31% | death_exit_long |
| 10 | long | macro | -0.44% | death_exit_long |
| 11 | long | macro | +0.64% | death_exit_long |
| 12 | long | macro | +1.72% | death_exit_long |
| 13 | long | macro | +0.94% | death_exit_long |
| 14 | long | macro | -0.47% | death_exit_long |
| 15 | long | macro | -0.32% | death_exit_long |
| 16 | long | macro | +0.61% | death_exit_long |
| 17 | long | macro | +0.20% | death_exit_long |
| 18 | long | macro | -0.89% | death_exit_long |
| 19 | long | macro | -0.56% | death_exit_long |
| 20 | long | macro | -0.30% | death_exit_long |
| 21 | long | macro | +0.51% | death_exit_long |
| 22 | long | macro | -0.38% | death_exit_long |
| 23 | long | macro | -0.25% | death_exit_long |
| 24 | long | macro | +0.08% | death_exit_long |
| 25 | long | macro | -0.09% | death_exit_long |
| 26 | long | macro | -1.13% | death_exit_long |
| 27 | long | macro | -0.93% | death_exit_long |
| 28 | long | macro | -0.41% | death_exit_long |
| 29 | long | macro | -0.91% | death_exit_long |
| 30 | long | macro | -0.28% | death_exit_long |
| 31 | long | macro | +0.33% | death_exit_long |
| 32 | long | macro | +4.07% | death_exit_long |
| 33 | long | macro | -0.25% | death_exit_long |
| 34 | long | macro | -2.00% | hard_stop_2pct |
| 35 | long | macro | -0.04% | death_exit_long |
| 36 | long | macro | -0.04% | death_exit_long |
| 37 | long | macro | -0.09% | death_exit_long |
| 38 | long | macro | -0.01% | death_exit_long |
| 39 | long | macro | -0.12% | death_exit_long |
| 40 | long | macro | -0.33% | death_exit_long |
| 41 | long | macro | -0.09% | death_exit_long |
| 42 | long | macro | -0.73% | death_exit_long |
| 43 | long | macro | -0.26% | death_exit_long |
| 44 | long | macro | -0.52% | death_exit_long |
| 45 | long | macro | -0.37% | death_exit_long |
| 46 | long | macro | -0.21% | death_exit_long |
| 47 | long | macro | +0.22% | death_exit_long |
| 48 | long | macro | -1.31% | death_exit_long |
| 49 | long | macro | -0.34% | death_exit_long |
| 50 | long | macro | -0.44% | death_exit_long |
| 51 | long | macro | -0.23% | death_exit_long |
| 52 | long | macro | -0.56% | death_exit_long |
| 53 | long | macro | -0.14% | death_exit_long |
| 54 | long | macro | +0.04% | death_exit_long |
| 55 | long | macro | -0.27% | death_exit_long |
| 56 | long | macro | -0.04% | death_exit_long |
| 57 | long | macro | -0.23% | death_exit_long |
| 58 | long | macro | -0.44% | death_exit_long |
| 59 | long | macro | +1.24% | death_exit_long |
| 60 | short | macro | -0.72% | golden_exit_short |
| 61 | short | macro | -0.19% | golden_exit_short |
| 62 | short | macro | -0.89% | golden_exit_short |
| 63 | short | macro | -0.18% | golden_exit_short |
| 64 | long | macro | +0.11% | death_exit_long |
| 65 | long | macro | -0.26% | death_exit_long |
| 66 | long | macro | -0.11% | death_exit_long |
| 67 | long | macro | +0.55% | death_exit_long |
| 68 | long | macro | +5.17% | death_exit_long |
| 69 | long | macro | +0.04% | death_exit_long |
| 70 | long | macro | -0.34% | death_exit_long |
| 71 | long | macro | -0.17% | death_exit_long |
| 72 | long | macro | -1.12% | death_exit_long |
| 73 | long | macro | -0.11% | death_exit_long |
| 74 | long | macro | -0.43% | death_exit_long |
| 75 | long | macro | -1.03% | death_exit_long |
| 76 | long | macro | +0.06% | death_exit_long |
| 77 | long | macro | -0.10% | death_exit_long |
| 78 | long | macro | -0.17% | death_exit_long |
| 79 | long | macro | -0.16% | death_exit_long |
| 80 | long | macro | +0.21% | death_exit_long |
| 81 | long | macro | -0.65% | death_exit_long |
| 82 | long | macro | +0.24% | death_exit_long |
| 83 | long | macro | -0.55% | death_exit_long |
| 84 | long | macro | -0.23% | death_exit_long |
| 85 | long | macro | +0.78% | death_exit_long |
| 86 | long | macro | -0.51% | death_exit_long |
| 87 | long | macro | +0.90% | death_exit_long |
| 88 | long | macro | +0.89% | death_exit_long |
| 89 | long | macro | +0.15% | death_exit_long |
| 90 | long | macro | -0.01% | death_exit_long |
| 91 | long | macro | -0.08% | death_exit_long |
| 92 | long | macro | +0.03% | death_exit_long |
| 93 | long | macro | +0.13% | death_exit_long |
| 94 | long | macro | +0.34% | death_exit_long |
| 95 | long | macro | +0.55% | death_exit_long |
| 96 | long | macro | -0.42% | death_exit_long |
| 97 | long | macro | -0.59% | death_exit_long |
| 98 | long | macro | -0.38% | death_exit_long |
| 99 | long | macro | -0.35% | death_exit_long |
| 100 | long | macro | -0.05% | death_exit_long |
| 101 | long | macro | -0.19% | death_exit_long |
| 102 | long | macro | -0.31% | death_exit_long |
| 103 | long | macro | +0.52% | death_exit_long |
| 104 | long | macro | -0.05% | death_exit_long |
| 105 | long | macro | -0.09% | death_exit_long |
| 106 | long | macro | +0.45% | death_exit_long |
| 107 | long | macro | -0.48% | death_exit_long |
| 108 | long | macro | -1.28% | death_exit_long |
| 109 | long | macro | +0.49% | death_exit_long |
| 110 | long | macro | -0.14% | death_exit_long |
| 111 | long | macro | -0.06% | death_exit_long |
| 112 | long | macro | -0.45% | death_exit_long |
| 113 | short | macro | +0.14% | golden_exit_short |
| 114 | short | macro | -1.59% | golden_exit_short |
| 115 | short | macro | +0.05% | golden_exit_short |
| 116 | short | macro | -0.04% | golden_exit_short |
| 117 | short | macro | +0.14% | golden_exit_short |
| 118 | short | macro | +0.38% | golden_exit_short |
| 119 | short | macro | -0.12% | golden_exit_short |
| 120 | short | macro | -0.04% | golden_exit_short |
| 121 | short | macro | -0.68% | golden_exit_short |
| 122 | short | macro | -0.59% | golden_exit_short |
| 123 | short | macro | -0.04% | golden_exit_short |
| 124 | short | macro | +0.44% | golden_exit_short |
| 125 | short | macro | -0.63% | golden_exit_short |
| 126 | short | macro | -0.70% | golden_exit_short |
| 127 | short | macro | -0.16% | golden_exit_short |
| 128 | short | macro | -0.41% | golden_exit_short |
| 129 | short | macro | -0.52% | golden_exit_short |
| 130 | short | macro | -0.43% | golden_exit_short |
| 131 | short | macro | -0.46% | golden_exit_short |
| 132 | short | macro | +1.10% | golden_exit_short |
| 133 | short | macro | -0.33% | golden_exit_short |
| 134 | short | macro | -0.05% | golden_exit_short |
| 135 | short | macro | +0.28% | golden_exit_short |
| 136 | short | macro | -0.67% | golden_exit_short |
| 137 | short | macro | +0.22% | golden_exit_short |
| 138 | short | macro | -0.26% | golden_exit_short |
| 139 | short | macro | -0.10% | golden_exit_short |
| 140 | short | macro | -0.12% | golden_exit_short |
| 141 | short | macro | -0.34% | golden_exit_short |
| 142 | short | macro | +0.87% | golden_exit_short |
| 143 | short | macro | +2.83% | golden_exit_short |
| 144 | short | macro | +0.56% | golden_exit_short |
| 145 | short | macro | -0.28% | golden_exit_short |
| 146 | short | macro | -0.13% | golden_exit_short |
| 147 | short | macro | -0.30% | golden_exit_short |
| 148 | short | macro | -0.22% | golden_exit_short |
| 149 | short | macro | -0.80% | golden_exit_short |
| 150 | short | macro | +1.19% | golden_exit_short |
| 151 | short | macro | -0.19% | golden_exit_short |
| 152 | short | macro | -0.68% | golden_exit_short |
| 153 | short | macro | -1.40% | golden_exit_short |
| 154 | short | macro | -0.65% | golden_exit_short |
| 155 | short | macro | +5.53% | golden_exit_short |
| 156 | short | macro | -0.58% | golden_exit_short |
| 157 | short | macro | -0.14% | golden_exit_short |
| 158 | short | macro | -0.18% | golden_exit_short |
| 159 | short | macro | +0.20% | golden_exit_short |
| 160 | short | macro | -0.28% | golden_exit_short |
| 161 | short | macro | +0.82% | golden_exit_short |
| 162 | short | macro | +0.04% | golden_exit_short |
| 163 | short | macro | -0.57% | golden_exit_short |
| 164 | short | macro | +1.44% | golden_exit_short |
| 165 | short | macro | -0.39% | golden_exit_short |
| 166 | short | macro | -0.05% | golden_exit_short |
| 167 | short | macro | -0.98% | golden_exit_short |
| 168 | short | macro | +5.76% | golden_exit_short |
| 169 | short | macro | -1.23% | golden_exit_short |
| 170 | short | macro | +1.33% | golden_exit_short |
| 171 | short | macro | +3.26% | golden_exit_short |
| 172 | short | macro | -2.00% | hard_stop_2pct |

## Reproducibility

```bash
cd okx-demo-bot
python -m research.run_benchmark          # uses data/ cache if present
python -m research.run_benchmark --refresh  # re-fetch public OHLCV
python -m pytest tests/ -q
```

Caches under `okx-demo-bot/data/` are gitignored. Commit this report; re-fetch to regenerate numbers on a new freeze date.
