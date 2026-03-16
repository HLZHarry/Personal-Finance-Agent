# Recurring Transaction Patterns — Canadian Banking Reference

Use this guide when interpreting output from `detect_recurring.py` and when
explaining projections to the user.

---

## 1. Income patterns

### Bi-weekly payroll (most common in Canada)
- **Gap:** exactly 14 days
- **Sign:** positive amount
- **Detection signal:** same employer name, exactly $X every 14 days
- **Day anchor:** not fixed to a calendar day — drifts through the month
- **Typical descriptions:** `PAYROLL DEPOSIT <EMPLOYER>`, `DIRECT DEPOSIT`
- **Edge case:** payroll lands on a weekend → deposited the preceding Friday.
  This can create a gap of 12 or 16 days around long weekends.  Allow ±3 days
  when detecting the gap.
- **Example:** Accenture Inc pays $6,500.00 every 14 days — detected as
  BI_WEEKLY FIXED.

### Semi-monthly payroll (twice a month, fixed dates)
- **Gap:** alternating ~15 and ~16 days (1st and 15th, or 15th and last)
- **Detection signal:** two deposits per month on near-fixed dates
- **Distinction from bi-weekly:** semi-monthly always lands on the same pair
  of calendar dates; bi-weekly drifts.

### Monthly salary
- **Gap:** 28–31 days
- **Example:** last business day of the month

### Government transfers
- **CPP / OAS:** 3rd-to-last business day of each month
- **EI:** bi-weekly, same weekday
- **GST/HST credit:** quarterly (January, April, July, October)
- **CRA description:** `CANADA REVENUE AGENCY`, `CRA TAX REFUND`

---

## 2. Housing payments

### Mortgage
- **Gap:** monthly, usually 1st of the month (some lenders use 15th)
- **Amount:** FIXED — principal + interest is constant for fixed-rate mortgages
- **Description pattern:** `MORTGAGE PAYMENT`, `RBC HOMELINE`, `TD MORTGAGE`
- **Edge case:** accelerated bi-weekly mortgages have a 14-day gap and a
  slightly different amount — detect as BI_WEEKLY FIXED
- **Detection confidence:** HIGH — same amount, same gap, same description

### Rent (e-transfer)
- **Gap:** monthly, often 1st or last day of the month
- **Amount:** FIXED if rent is the same each month
- **Challenge:** rent paid via Interac e-transfer shows up as
  `E-TRANSFER SENT <LANDLORD NAME>` — the script groups by exact description,
  so a consistent landlord name will be detected correctly
- **False positive risk:** multiple e-transfers to the same person for
  different purposes will inflate the detected amount

### Condo / strata fees
- **Gap:** monthly
- **Amount:** FIXED (unless a special assessment is charged)
- **Description:** often labeled as `CONDO FEE`, `STRATA FEE`, or a
  property management company name

---

## 3. Utility payments

All Canadian utilities bill monthly but with seasonal amount variation.

| Utility | Typical CV | Season effect | Notes |
|---------|-----------|---------------|-------|
| Natural gas (Enbridge) | 50–80% | 3-5x higher in winter | Wide range; use as VARIABLE |
| Electricity (Toronto Hydro, Hydro One) | 20–40% | 20-40% higher in summer/winter | VARIABLE |
| Internet (Rogers, Bell) | < 5% | None | FIXED (plan rate is constant) |
| Wireless phone | < 5% | None | FIXED unless overage charges |
| Water / sewer | 15–25% | Slight summer increase | VARIABLE |

**Key rule:** Internet and phone are FIXED even though they appear alongside
variable utilities — the plan rate does not change month to month.

---

## 4. Subscription patterns

Subscriptions are the most reliably FIXED recurring transactions.

| Service | Typical amount | Billing day | Notes |
|---------|---------------|-------------|-------|
| Netflix | $18.99–$22.99 | Same calendar day each month | Prices increase occasionally |
| Spotify | $11.99–$13.99 | Same day | Student/family plans differ |
| Apple (App Store) | $4.99–$14.99+ | Same day | May appear as `APPLE.COM/BILL` |
| Amazon Prime | $9.99/month or annual | Annual renewal date | Watch for large annual charge |
| Disney+ | $11.99–$13.99 | Same day | |
| Goodlife Fitness | $34.99–$54.99 | 1st or 15th | Contract vs month-to-month |
| Adobe Creative Cloud | $54.99–$84.99/month | Same day | May bill annually |

**Detection note:** Subscriptions often have exact-cent precision and never
vary — detect with CV threshold of 0.01 (1%) to catch rare price increases.

---

## 5. Recurring vs coincidental — decision rules

A transaction series is **genuinely recurring** when ALL of the following hold:

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| Occurrences | ≥ 3 | At least 3 data points to establish a pattern |
| Gap consistency | gap_stdev / gap_mean < 0.35 | Allows month-length variation (28 vs 31 days) |
| Gap plausibility | mean_gap between 6 and 120 days | Filters out daily noise and annual one-offs |
| Not one-time coincidence | Appears in ≥ 2 distinct calendar months | Prevents a cluster of same-week visits from looking monthly |

A transaction series is **coincidental (not recurring)** when:
- Same merchant, widely varying amounts AND widely varying gaps
  (e.g., Amazon purchases: different amounts, days apart or weeks apart)
- Appears in a single calendar month cluster
  (e.g., three gas fill-ups in one road trip week)
- Description is a person's name via e-transfer with no fixed amount or gap
  (e.g., `E-TRANSFER SENT MICHAEL CHEN` — amounts $150/$200/$250/$300, irregular timing)

---

## 6. Amount classification — fixed vs variable thresholds

```
coefficient_of_variation (CV) = stdev(amounts) / |mean(amounts)|

CV < 0.10  →  FIXED   (< 10% variation — price increases only)
CV < 0.35  →  STABLE  (predictable range — gas, groceries in bulk)
CV ≥ 0.35  →  VARIABLE (use median for projection, note wide range)
CV ≥ 0.70  →  HIGH_VARIANCE (flag to user; exclude from deterministic projection)
```

For projection purposes:
- **FIXED:** use the exact last known amount
- **STABLE / VARIABLE:** use the median (more robust to outliers than mean)
- **HIGH_VARIANCE:** show as a range (min–max) rather than a single number

---

## 7. Common detection edge cases

| Edge case | How to handle |
|-----------|--------------|
| Price increase mid-year (e.g., Netflix raises price) | Two sub-series with different amounts; the detector will show HIGH CV. Use the most-recent 3 occurrences to re-detect. |
| Accelerated bi-weekly mortgage | Detected as BI_WEEKLY, not MONTHLY. Amount is ~10% lower than a monthly payment. |
| Annual charge disguised as monthly | Amazon Prime sometimes billed annually — will appear as a single outlier, not a recurring series. |
| Pre-authorized debit vs manual | Both appear identically in Canadian bank exports; no distinction needed. |
| Duplicate NSF + re-charge | Same transaction appears twice on same date (bounce + retry). Filter: skip exact duplicate (date + amount + description). |
