# Supplier risk dataset: profile

`supplier_risk_dataset.csv`: 10,000 rows × 46 columns. No missing values, no duplicate IDs.

## Columns

- **Identity:** `supplierID` (SUPP_00001 to SUPP_10000) and `Supplier Name`. Names are synthetic: 64 stems such
  as "Global Logistics" with a number appended ("Global Logistics 175"). They are not real companies.
- **19 risk scores (0–100, integers, 100 = maximum risk)**, each with a matching `_Level` text column:
  `Total_Risk_Index` plus 18 category scores.
- **Operational metrics:**
  - `Purchase Order Volume (EUR)`: 10k to 50M, heavily skewed (skew 6.3). The top 1% of suppliers hold 16.6% of
    spend, and the values are clipped (21 at exactly 50M, 6 at exactly 10k).
  - `Order Change Rate`: 0–32%.
  - `Supplier Delivery Rating`: 65–100%; 1,547 suppliers sit at exactly 100.
  - `Order Confirmation Rate`: 61–100%.
- **Categories:** `Sourcing Risk Level` (Low / Medium / High) and `Supply Chain Complexity`
  (Simple / Moderate / Complex).
- **Missing compared with the brief:** there is no country, region, product category or component column, and
  ESG is a single score (no separate E, S and G pillars, although the description file mentions them).

## Levels are fixed bands (identical for every score)

| Level | Score |
|---|---|
| Low | 0–24 |
| Medium | 25–49 |
| High | 50–74 |
| Critical | 75–100 |

The `_Level` columns can be derived from the scores, so treat them as labels, not extra information.

## The Total Risk Index formula (exact for all 10,000 rows)

`Total_Risk_Index = round_half_to_even( Σ weight × score )`, with the weights summing to 100%:

| Weight | Scores |
|---|---|
| 10% | Operational_Resilience, Financial_Health, Quality_Risk |
| 8% | Compliance_Risk |
| 6% | Credit_Rating, Safety_Incident, Sub_Tier_Visibility |
| 5% | Geopolitical_Risk, Governance_Risk, ESG_Performance |
| 4% | Labor_Stability, Environmental_Exposure, Digital_Security, Industry_Benchmark, Political_Stability |
| 3% | Market_Sentiment, Media_Sentiment, External_Intelligence |

Verification: computing `Σ (weight in whole percent × score)` in integers, dividing by 100, and rounding half to
even (Python's `round`, NumPy's `np.round`) matches `Total_Risk_Index` on 10,000 of 10,000 rows. Rounding half up
fails on the 47 rows that land exactly on .5.

This means "why is the index high?" can be answered **exactly**: each score contributes weight × score points,
and its contribution compared with an average supplier is weight × (score − mean score).

## Distributions

- **Category scores:** mean about 50, sd about 20. Geopolitical, Political_Stability and Environmental_Exposure are
  narrower (sd about 16).
- **Total_Risk_Index:** mean 50, sd 14, range 6–93. Low 318, Medium 4,485, High 4,813, Critical 384.
- **Category scores move together:** median |r| between them is 0.47 and the highest pairs reach about 0.72
  (Safety ~ ESG, Benchmark ~ External intelligence). A supplier that is risky in one area tends to be risky in
  others.

## Relationships worth showing in the UI

- **Delivery performance tracks the risk scores:** Supplier Delivery Rating vs Operational_Resilience r = −0.77,
  vs Quality r = −0.78, vs Total_Risk_Index r = −0.71. Suppliers that break this pattern (low risk score but poor
  delivery, or the reverse) are worth flagging as "data and performance disagree".
- **Spend is unrelated to risk** (r = 0.01). 44 suppliers are both in the top 10% by spend and Critical. That's
  the real exposure list.
- **Sourcing risk goes with complexity and risk.** High sourcing risk (hard to replace): 3,502 suppliers, mean
  index 61, mostly Complex supply chains. Low: 3,474 suppliers, mean index 39, mostly Simple.

## The brief's example questions, answered from the data

- **"Which of SUPP_00012, SUPP_00450 and SUPP_00731 has the lowest financial risk?"** The answer depends on what
  "financial risk" means, and that ambiguity is the interesting part:

  | Supplier | Financial_Health | Credit_Rating | Weighted (10:6, as in the index) |
  |---|---|---|---|
  | SUPP_00012 | 54 | 57 | 55.1 |
  | SUPP_00450 | 65 | 58 | 62.4 |
  | SUPP_00731 | 53 | 76 | 61.6 |

  SUPP_00731 has the best financial health but the worst credit rating. Combined, SUPP_00012 is lowest. A good
  chatbot shows both scores and says so.

- **"Why is the Total Risk Index of SUPP_00018 so high?"** It's 80 (Critical, 98th percentile). Of the 30 points
  above an average supplier, the largest contributions are:

  | Score | Value | Weight | Points above average |
  |---|---|---|---|
  | Operational_Resilience | 95 | 10% | +4.5 |
  | Compliance_Risk | 98 | 8% | +3.8 |
  | Governance_Risk | 99 | 5% | +2.4 |
  | Quality_Risk | 74 | 10% | +2.4 |
  | Safety_Incident | 85 | 6% | +2.1 |