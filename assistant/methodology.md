# Persistence analysis methodology (plain language)

Each rule has an ID. Code in `src/cohort.py` uses the same IDs.

## R1 Index event: first fill
A patient's record starts on the date of their first pharmacy fill of the brand (BRAND_TRD). This date is the index date. Fills of other antidepressants are ignored when finding the index date. The original method uses the first fill anywhere in the data ("first_ever"). An alternative, tested in the sensitivity analysis, takes the first fill inside the intake window and ignores earlier fills ("first_in_window"); that alternative can wrongly count patients who were already on the drug as new starters.

## R2 Intake window
The index date must fall between 1 January 2022 and the last date that still leaves enough follow-up (12 months before the end of data under the original rules). The first year of data (2021) is kept free so every patient can have a full 12-month look-back.

## R3 Look-back: 12 months of continuous enrolment before the index date
The patient must have had insurance coverage with no break for the 12 months before the index date. Claims only exist while someone is insured, so without this rule a patient who joined the plan already taking the drug would look like a new starter. Coverage segments that touch (one ends the day before the next starts) count as continuous. Any break, even a short one, fails the rule.

## R4 Look-forward: 12 months of continuous enrolment after the index date
The patient must also have had unbroken coverage for the 12 months after the index date. Patients who lose or change insurance in that year are removed from the analysis entirely, even though persistence is only measured at 6 months. This guarantees every included patient is fully observed, but it removes people who change jobs or plans, who may behave differently from those who stay.

## R5 Allowed gap: 60 days
Each fill covers a number of days (the days' supply). A gap is measured from the day the supply runs out to the date of the next fill. If a gap is longer than 60 days, the patient is treated as having discontinued, on the day their supply ran out. A gap of exactly 60 days is allowed. The sensitivity analysis tests 30 and 90 days.

## R6 Early refills carry forward
If a patient refills before their previous supply runs out, the leftover days are added on, so the supply end date moves forward by the full new supply. Early refills are not double counted as overlapping days.

## R7 Persistence measure: still on therapy at 6 months
A patient is persistent at 6 months if they have not discontinued (under R5) before day 182 after the index date. The headline figure is the number of persistent patients divided by the number of patients in the analysis cohort (those passing R1-R4).

## R8 Time-to-discontinuation view: Kaplan-Meier curve
Instead of one 6-month number, the Kaplan-Meier curve shows the share of patients still on therapy on every day after the index date. Patients whose coverage ends before they are seen to stop are "censored": they count while observed and then leave the calculation without being counted as stopping. This lets the analysis keep patients who fail R4 instead of dropping them. Censoring assumes that patients who lose coverage are otherwise similar to those who stay; if they actually stop more often, the curve is still somewhat optimistic, so a worst-case figure (all censored patients counted as stopped) is also reported.

## A1 Data used
The analysis uses synthetic pharmacy claims (fill date, drug, days' supply) and enrolment periods for 6,000 patients, generated with a fixed random seed (42) by `src/generate_data.py`. No real patient data is used. The generator was tuned so the original rules give a figure close to the reported 68%.

## A2 Limits of pharmacy claims
Pharmacy claims only record prescriptions that were filled and paid for through insurance. They do not show prescriptions that were written but never filled, cash payments, free samples, why a patient stopped, or whether a patient actually took the medicine they collected.
