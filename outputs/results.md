# Analysis results (synthetic data, seed 42)

Each result has an ID. The methodology assistant cites these IDs.

## O1 Headline result (original method)
Using the original rules (R1-R7: first-ever fill, 12-month look-back, 12-month look-forward, 60-day gap), 68.2% of the 3010 patients in the analysis cohort were persistent at 6 months. This reproduces the reported 68% figure.

## O2 Who was excluded (attrition)
Of 5998 patients with at least one fill: included: 3010; R2: index outside intake window: 1584; R4: failed look-forward enrolment: 833; R3: failed look-back enrolment: 571.
The 12-month look-forward rule (R4) alone removes 833 patients who lost or changed insurance within a year.

## O3 Effect of the allowed gap (R5)
Holding other rules at the original values, 6-month persistence is 41.5% with a 30-day gap, 68.2% with a 60-day gap and 81.2% with a 90-day gap. The gap rule is the single biggest driver of the number.

## O4 Effect of the 12-month look-forward (R4)
Dropping the look-forward requirement and using Kaplan-Meier with censoring (R8) grows the cohort from 3010 to 4446 patients and gives 64.5% persistent at 6 months. If every patient who lost coverage before 6 months is assumed to have stopped (worst case), it is 57.8%. Patients who lose coverage stop therapy more often, so requiring 12 months of coverage makes the remaining cohort look more persistent.

## O5 Effect of how the first fill is identified (R1, R3)
With no look-back and the index taken as the first fill inside the intake window, prevalent users (already on the drug when they joined the plan) are counted as new starters. The cohort grows to 3840 and persistence is 69.8%. The 12-month look-back protects the original figure from this bias, so this choice moves the number only modestly.

## O6 Time to discontinuation
Under the original rules the Kaplan-Meier curve shows 83.3% of patients still on therapy at 3 months, 68.2% at 6 months and 48.4% at 12 months; the median time on therapy is 348 days. A single 6-month figure hides that about 53% of the 6-month drop-off has already happened by month 3.

## O7 Synthetic ground truth
Because the data is synthetic, the true 6-month persistence of all genuine new starters (counting fills after they lost insurance, with a 60-day gap) is known: 61.3%. The original method overstates this by 6.9 points, mostly through the look-forward rule. In real data this truth is not observable.

## O8 What claims data cannot see
Patients who were prescribed the drug but never filled it (primary non-adherence), patients paying cash and free samples do not appear in pharmacy claims. Doctors and the field team do see these patients, so their impression of early stopping includes people the claims analysis cannot count. This is not quantified in this analysis.
