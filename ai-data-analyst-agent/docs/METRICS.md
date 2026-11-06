# Metric and rule definitions

Every number in the UI is computed by the backend from the active dataset version, except forecasts and
statistical tests, which are model estimates and are labelled as such. This file is the reference for the
formulas and thresholds; the "How calculated" panel shows the formula and filters behind each result.

## Data cleaning (Phase 3b)

### Rows
- `rows_before` = every row in the source grid (title rows, blank rows, header rows, data, footers).
- `rows_after` = rows in the cleaned version.
- `rows_removed` = sum of rows removed by steps (empty rows, title + header rows, footer notes,
  verified total rows, keyed duplicate records). The pipeline checks
  `rows_before - rows_removed == rows_after` and fails with "Calculation check failed" otherwise.

### Cells changed
A cell is *changed* when its cleaned value, written in canonical text form, differs from the raw
cell text. Canonical forms: money `-1234.50` (no symbol, no separators, fixed scale), integers
`1234`, floats Python shortest repr (`0.125`), dates `YYYY-MM-DD`, date-times `YYYY-MM-DD HH:MM:SS`,
booleans `true`/`false`, text as trimmed/normalized. Empty raw cells and empty cleaned values are equal.

### Quality score (0-100)
`score = 100 × (0.4 × completeness + 0.4 × validity + 0.2 × uniqueness)`, rounded to 1 decimal.

| Part | Before cleaning | After cleaning |
|---|---|---|
| completeness | 1 − (empty cells + null-marker cells) ÷ cells, over the table below the header | 1 − empty cells ÷ cells |
| validity | share of non-empty raw cells already in canonical form | 1 − cells in columns flagged for review (kept as text because of ambiguity or mixed values) ÷ cells |
| uniqueness | 1 − share of exactly repeated rows | 1 − share of exactly repeated rows |

### Thresholds
- Encoding: text that was saved as UTF-8 but read as Windows-1252 (`CafÃ©`, `â‚¹`) is repaired first,
  before any other step, so a garbled `₹` can never turn into a digit.
- Type conversion: a column becomes numeric/date only if at most **10%** of its non-empty values fail
  (or a single value in a column of 8 or more); failures become empty and are listed with examples as
  warnings. Otherwise the column stays text and is flagged. The original file always keeps the value.
- Date detection: at least 50% of values look like dates (or 80% for columns whose name suggests a
  date). Inside a clearly-dated column, Excel serial numbers (20000-80000) and `20240110` are read too.
  Ordinals (`7th Jan 2024`) are accepted. Values with a time zone (`Z`, `+05:30`) are converted to UTC.
  A year-first date whose middle part is above 12 (`2024-13-01`) is read as year-day-month, with a warning.
- Day/month order: any first part above 12 means day-first; any second part above 12 means
  month-first; otherwise the dataset option `date_order` (default DMY) is used with a warning.
- Decimal separator: decided from unambiguous values (`1,234.56`, `12,5`, `1.234.567`...). Values
  like `1,234` alone are ambiguous: the column uses the separator settled by other columns in the
  dataset, or `.` when the currency symbol is $, £, ₹ or ¥; otherwise it stays text with a warning.
- ID-like columns (kept as text): leading zeros, ID-like names (`id`, `code`, `sku`, `zip`, `phone`,
  `account`, ...), or fixed-length unique digit strings of 5+ digits.
- Money: a currency symbol on at least 50% of values, or a money-like column name. Stored exactly as
  DECIMAL(38, scale), scale = max(2, decimals seen), capped at 6. The currency comes from the symbol, or
  from the column name (`Amount (INR)`) when values carry none. Indian grouping (`1,20,000`) is supported.
- Number forms: scientific notation (`1.2E+05`), magnitudes (`12k`, `3.5M`, `2bn`, `1.5 lakh`, `2 crore`),
  counted things (`3 pcs`, `5 stars`) and scores with one shared denominator of 5, 10 or 100 (`3/5` -> 3).
- Units: a column whose values all use units of one kind (mass, length, volume or duration) is converted to
  the unit used most often (`500 g` -> 0.5 when kg dominates); the unit is added to the column name.
  Columns mixing kinds of units stay text.
- Percentages: when a column mixes `10%` with bare values of 1 or less (`0.15`), the bare values are
  already ratios and are not divided by 100.
- Total rows: a row whose first text column reads `Total`, `Subtotal` or `Grand total` is removed only
  if every numeric value equals the sum of the rows above it (since the previous total, or all rows
  above): exact for integers, within 1 minor unit for money, within max(1e-9 relative, 0.005) for
  floats. Otherwise it is kept and flagged.
- Category variants: values that differ only by case, spacing or punctuation are merged into the most
  frequent spelling (ties: the properly capitalised spelling, then first seen). Numbers are never merged
  (`-2` and `2` stay different).
- Casing: when at least 60% of a category column's distinct labels are in Title or mixed case, labels
  written all lower or ALL CAPS follow suit (`BOMBAY` -> `Bombay`); codes of 3 letters or fewer stay.
  Person-name columns: words written all lower or ALL CAPS are capitalised (`john SMITH` -> `John Smith`).
- Emails (90% of values look like addresses, or 60% with an email-like name): lower-cased and trimmed;
  invalid addresses are kept and reported.
- Phone numbers (phone-like name, 60% of values with 7-15 digits): spaces, brackets and dashes removed,
  a leading `+` kept; no country code is added. Other values are kept and reported.
- Repeated IDs: when an ID column is at least 80% unique, IDs that appear on different records are
  reported (not removed).
- Exact duplicate rows are removed automatically only when the table has an ID-like column.

### Tier 2 suggestion thresholds
- Outliers (screening): outside Q1 − 1.5×IQR … Q3 + 1.5×IQR, at least 8 values.
- Near-duplicate spellings: similarity ratio ≥ 0.9 (difflib), among the 300 most frequent values.
- Near-constant column: one value covers ≥ 99% of at least 20 rows.
- Combined column: ≥ 90% of values look like `A, B`.
- Unit suffixes: ≥ 90% of values look like `1.2K`, `3M`, `5kg` (only for columns the automatic step left as text).
- Placeholder dates: 1900-01-01 or earlier (default action: set to empty).
- Ratings: a rating/stars column with ≥ 85% of values between 0 and 5 flags values outside 0-5.
- Wide format: 3+ numeric columns named like periods (months, years, `2024-01`, `Q1`).

## Statistics in column profiles
- Statistics skip empty values. Mean and median are shown separately.
- Money sums and means are exact decimals; the money mean keeps scale + 4 decimals and is rounded
  only for display (2 decimals).

## Analytics engine (Phase 4)

### General rules
- Every result reports `rows_in` (after filters), `rows_used` and `rows_skipped`; the engine checks
  `rows_in = rows_used + rows_skipped`.
- Empty values are skipped, never treated as 0. Comparison filters (`=`, `≠`, `>`, `in`, `not in`, ...)
  never match empty values (SQL semantics); use `is empty` to select them.
- Rows whose group-by value is empty form their own group, shown as "(empty)".
- Money is aggregated in exact integer minor units. Sums, minimums and maximums are exact; the mean
  is an exact decimal division (34 significant digits); the median of an even count is the exact
  midpoint. Values are rounded only for display (2 decimals for currency).
- Reconciliation before returning: group totals equal the grand total (exact for money and integers,
  relative 1e-9 for floats); group row counts add up; shares add up to 100% within 1e-9; period
  totals add up to the grand total. A failed check returns "Calculation check failed".

### Dual-engine verification
DuckDB recomputes each plan independently from the same Parquet file (money as DECIMAL), applying
the filters itself. Group values must match exactly for money/integer sums, minimums, maximums and
counts, and within a relative 1e-9 otherwise. A mismatch returns "Calculation check failed".

### Definitions
- **Share of total** = group value ÷ total of all groups. Shown only for sums and counts when every
  group value is ≥ 0 and the total is not 0.
- **Growth %** = (current − previous) ÷ |previous|. "n/a" when the previous value is 0, missing, or
  either period is partial.
- **Time grains**: day, ISO week (Monday start, labelled `2024-W05`), calendar month, quarter, year.
  Missing periods inside the range count as 0 for sums and counts and as empty for other aggregations.
- **Partial period**: the first period is partial when the data starts after its first day; the last
  period is partial when the data ends before its last day. Partial periods are flagged and excluded
  from growth.
- **Trend sample size**: fewer than 8 complete periods → warning "too few points to judge a trend".
- **Average order value** = total revenue ÷ distinct order IDs (rows with a revenue value). Without an
  order ID column: total revenue ÷ rows, labelled "Average per row".
- **Outlier screening**: values outside Q1 − 1.5×IQR … Q3 + 1.5×IQR (at least 8 values). Screening only.
- **Correlation (profile)**: Pearson over rows where both values exist (pairwise), at least 3 rows; the
  matrix shows the number of rows per pair. Association, not causation.

## Automated insights (Phase 4d)

Insights are found by deterministic code; aggregates come from the verified query engine (Pandas +
DuckDB), statistics from SciPy. Headlines use fixed templates. Every insight lists caveats and
"possible next checks" (suggestions, never causes). Results are exploratory: at most **20** statistical
tests run per request, so individual p-values deserve multiple-comparison caution.

| Detector | Runs when | Reported when | Severity |
|---|---|---|---|
| Top contributor | a measure and a category with 2-200 values; all group sums ≥ 0 | top share exceeds an equal share by > 5 points | important: share ≥ 50% with ≥ 3 groups; notable: ≥ 1.5× equal share |
| Concentration (Pareto) | ≥ 5 groups | top 20% of groups hold ≥ 60% | important: ≥ 80% |
| Trend | a date column; ≥ 8 complete periods | linear regression p < 0.05 and change over the period ≥ 10% of the mean | important: p < 0.01, change ≥ 20%, R² ≥ 0.5 |
| Period change | ≥ 2 complete periods | last vs previous complete period, \|growth\| ≥ 20%; year-over-year (monthly, ≥ 13 months) ≥ 10% | notable: ≥ 50% (YoY ≥ 25%) |
| Weekday pattern | ≥ 2 full weeks, ≥ 2 values per weekday | Kruskal-Wallis p < 0.05 and (max − min weekday mean) ÷ overall mean ≥ 0.3 | notable |
| Anomaly (screening) | ≥ 8 complete periods | a period outside 1.5×IQR **and** \|robust z\| > 3.5 (z = 0.6745·(x − median) ÷ MAD) | notable |
| Relationship | two numeric columns, n ≥ 30 rows with both | \|Pearson r\| ≥ 0.5 and p < 0.05 (Spearman also shown) | important: \|r\| ≥ 0.8 and p < 0.001 |
| Segment difference | two largest groups with ≥ 10 values each | Welch t-test (both n ≥ 30, Cohen's d ≥ 0.5) or Mann-Whitney U (rank-biserial ≥ 0.3), p < 0.05 | notable |
| Distribution | ≥ 30 values | \|skewness\| > 1 or \|mean − median\| ≥ 20% of the median | notable: \|skew\| > 2 |
| Data quality | always | > 20% empty; cleaning converted > 10% of a non-text column; unapplied suggestions; unverified Total rows kept | important: unverified Total rows |

- **Time grain**: the coarsest of quarter / month / week / day where ≥ 80% of periods contain data and
  there are at least 10 periods; otherwise the finest well-filled grain (the trend is then skipped).
  This keeps empty, zero-filled periods from inflating the number of points.
- **Score** = effect size × share of the data involved × statistical strength (1 − p for tests, 1 for
  descriptive facts). Overlapping insights (top contributor / concentration on the same columns) are
  de-duplicated, keeping the higher score. Ranking: severity, then score; top N (default 10).
- Detectors that cannot run are listed with the reason (for example "Not enough data to call a trend").
- **AI wording** (optional): only the verified insight payloads are sent. Every number in the AI text
  must match a number in those payloads (relative 0.5%, or within rounding of the displayed value);
  others are marked "[unverified]" and the event is logged.

## Automatic dashboard

`app/analytics/dashboard.py` chooses plans; `run_verified` computes every number.

- **Measure:** the saved/detected revenue role, else quantity, else the first numeric column that is not an
  ID, percent, or label-like integer (year, month, code, zip, phone...). Default aggregation is the
  average for rates and positions (price, rate, score, rating, age, temperature, margin, lat/lon) and the
  total otherwise. With no numeric column the dashboard counts records.
- **Dimensions:** string columns with semantic type `category` and 2-200 distinct values, those with at
  most 30 values first, then schema order. The first three get breakdown tiles.
- **KPIs:** primary measure; records; average per record (when the primary is a total); a second measure.
  Change = growth of the last complete period vs the one before (engine trend growth, partial periods
  excluded). No change is shown when either period is partial, missing or zero.
- **Grain (auto):** span <= 62 days: day; <= 26 weeks: week; <= 4 years: month; <= 12 years: quarter;
  else year. The span is measured after filters.
- **Tiles:** trend (line, area above 24 points); one donut for the first additive breakdown with <= 6
  groups; other breakdowns as top-8 ranked bars with the remainder reported as "not shown"; a stacked
  trend by the first category with <= 6 values (stacked only for totals/counts and <= 36 periods); a
  summary table (top 15) whose columns are separate verified results joined on the group key.
- **Filters:** date range (`>=` from; `<=` to, or `<` the next day for datetime columns so the end day is
  whole) and `in` filters on dimension columns. Date presets in the UI are relative to the newest date in
  the data, not today.

## Auto charts (chart suggestions)

- **Menu (rules):** for up to 3 measures (default aggregation) and up to 4 dimensions: trend over time
  (date column, auto grain), ranked top-10 bars per dimension, donut for additive measures over <= 6 groups,
  average-per-record comparison (for totals), stacked trend by a <= 6-value dimension, and the mix of a
  second small dimension within the first (100% stacked for totals). Scores favour the primary measure and
  the first dimensions; the rule pick keeps the top 6 with at most two per family.
- **AI pick:** the model receives column metadata (name, type, meaning, distinct and empty counts) and the menu
  (id, chart, title, purpose); never rows. It returns ids and one-sentence reasons. Only menu ids are used.

## Reports

- Facts = dashboard KPIs, charts and summary table for the chosen date range (and category filters), insights
  for the date range, cleaning summary and column dictionary. The AI receives these facts with values already
  formatted and must copy numbers; `check_numbers` marks any number that does not match (0.5% / rounding
  tolerance) as "[unverified]". Template narrative: record count and span, the primary KPI and its change, the
  most important insight, insight headlines, and next checks as recommendations.

## Ask

- Plans come from the rule parser or an AI-filled template; either way the plan is validated against the
  schema and run with `run_verified`. Category filter values must exist in the column (matched
  case-insensitively and mapped to the stored spelling). A year in the question becomes
  `date >= YYYY-01-01 and date < (YYYY+1)-01-01`.
- Answer sentences: total/average/etc. for a single value; the highest (or lowest) group with its share of
  the total for rankings; first and last complete period with the change for trends.

## Forecast

- Ordinary least squares on the complete periods of the dashboard trend (at least 6), x = period index.
- 80% prediction interval: t(0.9, n-2) * s * sqrt(1 + 1/n + (x0 - mean x)^2 / Sxx), s from the residuals.
- When every observed value is >= 0, the forecast and its lower bound are floored at 0.
- A trailing partial period is forecast in full. The forecast is a model estimate, not a verified figure.

## Targets

- Progress = KPI value in the current view / target, computed by the backend; "at least" targets are met at
  progress >= 1.

## Pivot tables
- **Fields:** one to three row fields (nested, with a subtotal row for each parent), at most one column field and
  one to six values (sum, average, median, minimum, maximum, count, distinct count; or a row count). A date field
  in Rows or Columns is grouped by day, week, month, quarter or year. Filters are the dashboard's `in` filters.
- **Calculation:** every level (cells, subtotals, row totals, column totals, grand total) is its own group-by over
  the filtered rows, never a sum of other cells, so averages, medians and distinct counts are right at every
  level. Money is added as integer minor units; counts are exact integers.
- **Verification:** each group-by is recomputed in DuckDB and every group is compared (value and rows used):
  exact for money/integer sums, minimums, maximums and counts, relative 1e-9 otherwise. For sums and counts the
  cells and the rows must also add up to the grand total. Any difference returns "Calculation check failed" and
  no table is shown.
- **Empty values:** a value skips the rows where its own column is empty (never treated as 0). Rows whose Rows or
  Columns field is empty are listed as (empty). Periods that have no rows are not listed (the dashboard trend, by
  contrast, fills gaps with 0).
- **Partial periods:** the first and last period are marked "(partial)" when the data does not cover them fully.
- **Size:** no limit on the rows of the dataset (up to the upload cap, 3,000,000 rows). Only the output is bounded:
  500 columns and 600,000 cells; a larger pivot returns a message asking for a filter, Top N or fewer fields.
  Top N keeps the first-level rows with the largest value of the chosen measure; totals still include every row.
- **Order:** automatic = periods in time order, other fields by the first value, largest first. Rows can also be
  sorted by name or by a chosen value; columns by name or by value.
- **Show values as:** % of grand total, % of row total, % of column total and % of parent (sums and counts only),
  computed in the browser from the verified figures; other aggregations always show their values.
- **Excel export:** values as numbers with number formats, subtotals in bold, a frozen header; it exports the
  values, not the percentage views.

## Import from a link
- Google Sheets links are exported as CSV of the open tab (`gid`); other links must return a .csv, .xlsx
  or .xls file. The file then goes through the same checks and cleaning as an upload.
- Safety: https only, no credentials in the link, every hop including redirects must resolve to a public
  IP address (private, loopback, link-local and reserved ranges are refused), at most 4 redirects, the
  upload size limit and a 25 s timeout.
- Refresh downloads the link again. If the bytes are identical (SHA-256) nothing changes; otherwise the new
  file is stored alongside the old one (raw files are never overwritten) and cleaned into a new version
  with the dataset's existing cleaning options.
