# Research summary (2026-11-16)

Frozen notes from the offline study that produced `spec_v1`. Candles were Binance BTC/USDT (spot for the grid, USDT-M perp for the long/short study). Costs below are the research model: signal on the close, fill on the next open. This file does not re-run that study. The bot's replay uses the same rules on whatever OKX window you give it; it will not reproduce these tables tick for tick.

SPEC v1 is a paper benchmark. The out-of-sample Sharpe is about half a standard error, the walk-forward re-selection of this family lost money, and the mild drawdown is mostly the cash sleeve.

## Baseline: SMA 10/30

Next open, 0.10% fee + 0.05% slip, 50% of cash, $200 start. Full sample roughly 2020-01-01 through 2026-11-16.

| Timeframe | Strategy | Buy-and-hold 100% | Trades | Win rate |
| --- | ---: | ---: | ---: | ---: |
| 15m (old default) | −99.92% | +803% | 10,098 | 23% |
| 1h | −32% | +805% | 2,411 | 29% |
| 4h | +85% | +807% | 608 | 33% |

15m has no edge even with fees set to zero (+94% versus buy-and-hold +803%). 1h has a gross edge that fees erase. 4h SMA 10/30 survives costs and still loses to buy-and-hold. That book stays available as `--strategy sma_10_30` and is not the default.

## What cleared a pre-registered in-sample and out-of-sample check

Train 2020–2024, single test 2025-01-01 through 2026-11-16. The only textbook rule that beat 100% buy-and-hold on Sharpe **and** total return on both sides of that split was **4h EMA 50/200** (about 8-day / 33-day on a 4h chart): in-sample about +1,390% versus buy-and-hold about +1,199%, in-sample max drawdown about −59%. Out of sample: **+9.70%**, Sharpe **0.32**, max drawdown **−27%**, 24 trades, versus buy-and-hold **−30.5%** (drawdown −53%). It lagged buy-and-hold in 2023–2024. Nothing on 1h cleared the same bar. ATR and 200-day filters on SMA 10/30 reduced damage and did not produce an edge.

## SPEC v1

A later pre-registration searched 4h EMA/EMA and EMA/SMA lengths (fast 10–60 step 5, slow 80–250 step 10) on **2020–2024 only**, then ATR 3×/4× exits, then a fixed 15% vol target. The 2025–2026 window was scored once.

- The 3×3-smoothed Sharpe peak was the edge cell **EMA 10 / SMA 230** (smoothed Sharpe 1.535). Neighboring slow lengths 210–250 on fast=10 are all about 1.50–1.59 raw Sharpe. EMA 50/200 sits in a flat region of the EMA/EMA surface (smoothed 1.39 versus family best 1.41), not at the peak. A five-year Sharpe has a standard error near 0.45, so the grid does not separate these cells.
- ATR trails cut drawdown and failed the Sharpe rule (more trades, fees 17–41% of gross).
- Vol targeting on 10/230 was adopted on the pre-registered rule: in-sample Sharpe 1.556 versus 1.507, max drawdown **−19.1% versus −49.5%**, CAGR **+27% versus +77%**. ATR/close annualized with `sqrt(365.25*6)` is a range, not a close-to-close standard deviation, so the book is much smaller than “15% vol” sounds. Out of sample the average fill was on the order of $60 on a ~$210 book.

Single out-of-sample pass (spot, 0.10% + 0.05%):

| Rule | Return | CAGR | Max DD | Sharpe | Trades | Win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SPEC v1 (10/230, vol 15%) | +5.84% | +3.08% | −9.33% | 0.37 | 46 | 17.4% |
| Buy-and-hold 100% | −30.52% | −17.67% | −53.45% | −0.24 | 1 | — |
| 4h EMA 50/200, 100% | +9.70% | +5.07% | −27.25% | 0.32 | 24 | 33.3% |

Costs were 26% of SPEC's gross PnL. Beating buy-and-hold in that window is mostly being only partly invested in a down market. 50/200 made more money with a deeper drawdown. Swapping back to 50/200 after seeing this table would be a new experiment; the paper bot runs both, unchanged.

## Shorts and the ADX filter

Second pre-registration: the same two signals, long-only versus 1x long/short, ADX(14) z-score thresholds none / 0 / 0.5, with and without the 15% cap. Perp prices, OKX taker 0.05% + 0.05% slip, Binance funding until OKX history begins (2026-08-10; 7,534/7,534 settlements matched; overlap MAE about 0.24 bp). 2025–2026 was already contaminated for the long-only rules. A 2-year train / 6-month test walk-forward is the cleaner read.

- Step A did not select the ADX filter. Step C did not select shorts. The primary package was again 10/230, long-only, no filter, vol 15% (in-sample Sharpe 1.33, return +177%, max drawdown −23%).
- Unfiltered 10/230 shorts at 100% size: short-side net **−$161** (price about −$168, funding about +$108, fees about −$101). The vol-sized short net was about +$8 and did not beat the matched long-only Sharpe (1.311 vs 1.334).
- Walk-forward re-selection: **−15.8%**, Sharpe −0.04, max drawdown −43% ($200 → $168). Five of ten folds picked long-short; the short book was negative in four of those five. Four folds picked an ADX threshold; the sample in each fold is too small to promote it. One in-sample cell (z>0.5, 100% size) showed a profitable short book and was not selected. It stays unused.
- The frozen 10/230 vol book on the same test windows shows about +63%. Most of those years sit inside 2020–2024, the sample that chose it. That path is not a confirmation.

An external review of the design and of the results agreed: do not add shorts, do not add the ADX z-filter, keep the result paper-only, and do not open 2025–2026 again for leftover cells.

## What the paper bot is for

Run the three books side by side and read the fill logs. Do not retune 10/230, do not turn shorts or ADX on, and do not fund a live account from this study.
