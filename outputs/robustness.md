# Robustness checks (synthetic data)

## Sampling uncertainty, seed 42
- Original rules: 68.2% of 3010 patients, 95% Wilson interval 66.5-69.8%.
- Original rules at 3 months (Kaplan-Meier): 83.3%, 95% Greenwood interval 82.0-84.6%.
- No look-forward at 6 months (Kaplan-Meier, n=4446): 64.5%, 95% Greenwood interval 63.1-66.0%.

## What dropping the look-forward actually changes, seed 42
The cohort grows from 3010 to 4446 patients, but only part of that is R4. 3843 patients have index dates inside the original intake window (3010 plus the patients R4 excluded). The other 603 enter because R2 no longer needs 12 months of follow-up, so later index dates qualify.
Keeping only the same intake window gives 64.1% (95% interval 62.6-65.7%), or 57.6% if every patient lost before 6 months counts as stopped.

## Spread across 10 generator seeds (mean, min-max)

| Scenario | 6-month persistence |
|---|---|
| original | 68.6% (67.3-69.9%) |
| gap_30 | 43.0% (41.5-44.0%) |
| gap_90 | 80.8% (79.9-81.5%) |
| no_lookforward | 65.1% (64.1-66.9%) |

Original rules minus synthetic truth: mean 7.0 points (range 6.2 to 7.6).

## Stress test: coverage loss unrelated to patient risk (seed 42)
Same average coverage loss (25%), but high-risk patients are no more likely to lose it.
- Original rules: 63.3% (n=3121).
- No look-forward, Kaplan-Meier: 63.6% (n=4411).
- Synthetic truth: 62.1%.
