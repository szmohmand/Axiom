# Third-party provenance and license notices

AXIOM v2 includes two *adapted/ported methods* from publicly accessible MIT-licensed projects. It does **not** contain their complete applications, trained models, original backtest datasets, or reported performance histories.

## aaryann123/kalshi-bot

Repository: https://github.com/aaryann123/kalshi-bot
Source inspected: `bot.py` (functions `fair_yes`, `fee`, market entry screening), default branch on November 15, 2026.

AXIOM adapter: `app/ensemble.py` (`aaryann_fair` forecasting engine; `taker_fee` indicative fee formula). Differences: no Kalshi authenticated trading, no live order placement, and a common AXIOM data-normalization pipeline. Same public fair-probability equation and five-minute momentum coefficient as the source.

> MIT License
>
> Copyright (c) 2026 Kalshi Bot contributors
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## jaldrich2023/KalshiBot

Repository: https://github.com/jaldrich2023/KalshiBot
Source inspected: `KalshiBot/Engine/Predictor.swift` (`FeatureExtractor.features`, `headStart`), default branch on November 15, 2026.

AXIOM adapter: `app/ensemble.py` (`kalshibot_headstart`). This ports the public **head-start normalized distance** computation and maps it through a normal CDF for comparison. It is **not** the original Swift app's trained, market-anchored logistic predictor. It must not inherit that project's reported win rate.

> MIT License
>
> Copyright (c) 2026 I'm The Team, LLC
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## Other candidate repositories

They are linked in `research_sources/full_catalog.csv` and may have **different or absent licensing**. Their source code is not copied into AXIOM v2. The catalog and optional downloader do not automatically execute, import, or deploy external code.
