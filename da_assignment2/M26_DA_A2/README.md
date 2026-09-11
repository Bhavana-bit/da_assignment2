# Data Analytics I Assignment 2

## Bottom-Up Cube (BUC)

`buc.py` implements an iceberg Bottom-Up Cube from scratch in Python. It does
not use pandas grouping, a database engine, or a prebuilt cube operation.

### API

```python
from buc import buc, timed_buc

cells = buc(records, dimensions, measure="count", minsup=25)
timed = timed_buc(records, dimensions, measure="count", minsup=25)
```

The required primary measure is `COUNT(*)`, selected with `measure="count"`
(the equivalent spellings `count(*)` and `COUNT(*)` are also accepted). Each
result is structured as:

```text
{"dimensions": {"dimension_a": value, "dimension_b": "ALL"}, "measure": count}
```

`ALL` denotes an aggregate over that dimension. Dimension keys always appear
in the order supplied to `buc`.

### Algorithm

1. Materialize the input iterable once and validate dimensions, records,
   measure, and `minsup`.
2. At a recursion node, emit the current selected prefix with `ALL` for every
   unselected dimension when its support reaches `minsup`.
3. For each remaining dimension, partition the current records by observed
   values.
4. Discard partitions smaller than `minsup`.
5. Recursively process surviving partitions using only later dimensions.

Because each selected-dimension subset is formed recursively, cells such as
`(ALL, value)` and `(value, ALL)` are both generated. The algorithm never
constructs the Cartesian product of all dimension domains. A sorted value
ordering makes output deterministic, and the requested dimension order is
preserved in every result cell.

For `n` dimensions, recursion visits only observed, support-qualified
partitions and cube cells. Its memory use is dominated by the current
partition lists and the returned iceberg cells; `minsup` pruning reduces both
when many groups are sparse.

### Tests

Run the focused BUC tests with:

```bash
python3 -m unittest -v test_buc.py
```

## DuckDB Validation

`validate_buc_duckdb.py` is a separate reference validator. It runs DuckDB's
equivalent query:

```sql
GROUP BY CUBE (sex, race, marital_status, tax_filer_status,
                      employment_status, class_of_worker, education,
                      industry_code_major, occupation_code_major,
                      household_summary, region_prev_residence,
                      state_prev_residence)
HAVING COUNT(*) >= minsup
```

DuckDB output is normalized from `NULL` to `ALL` and compared with the
in-memory BUC output by cell key and support. DuckDB is imported only by this
validation module; it is not used by `buc.py`.

Run the manageable exact 12-dimension comparison with the workspace
environment:

```bash
.venv/bin/python validate_buc_duckdb.py M26_DA_A2_Part2.csv \
   --sample-size 500 --minsup 50 \
   --output duckdb_validation_sample.json
```

The validated sample produced 4,318 BUC cells and 4,318 DuckDB cells, with
zero cells only in either result, zero support mismatches, and maximum absolute
support difference 0. A full 299,285-row attempt at `minsup=10,000` exceeded
the available DuckDB memory while materializing the 12-dimensional CUBE
intermediate; this does not affect BUC execution or its independent sample
validation.

## Out-of-Memory BUC

`buc_out_of_memory.py` implements the same recursive BUC traversal with
temporary disk-backed partitions. It does not call `buc.py`, pandas, or
DuckDB. `buc_out_of_memory_csv` reads a CSV through `csv.DictReader`, stages
records incrementally, and recursively reads partition files in bounded pages.

```python
from pathlib import Path
from buc_out_of_memory import buc_out_of_memory_csv

result = buc_out_of_memory_csv(
   Path("M26_DA_A2_Part2.csv"),
   dimensions=["sex", "race", "education", "industry_code_major"],
   minsup=25,
   memory_limit_rows=17,
)
```

`memory_limit_rows` is the maximum number of rows retained across active
partition buffers before they are flushed to temporary pickle files. Read pages
are capped at the same size. It is a measurable row-count budget, not a byte
limit and not a process-RSS measurement. The result reports both the configured
budget and `estimated_peak_buffer_rows`; the latter counts algorithm-managed
source/page/buffer rows and is explicitly an estimate.

Instrumentation includes runtime, estimated peak rows, spilled partition count,
bytes written to spill files, processed pages, staged input rows, and staged
input bytes. Temporary files are held under `TemporaryDirectory` and removed
automatically on normal completion or exceptions.

On a 1,000-row sample using four dimensions, `minsup=25`, and
`memory_limit_rows=17`, in-memory and out-of-memory BUC both produced 97 cells.
The disk-backed run spilled 754 partitions, wrote 1,776,076 spill bytes, and
processed 842 pages.

## In-Memory/Paged Equivalence Test

`validate_buc_equivalence.py` loads one logical input and passes the same
records, dimension order, and support threshold to both implementations. It
canonically sorts complete cell outputs, then compares cell keys and support
counts. It reports cells only in either implementation, support mismatches,
maximum absolute support difference, and the first mismatch if a run fails.

Run the multi-configuration test with:

```bash
python3 validate_buc_equivalence.py M26_DA_A2_Part2.csv \
   --sample-size 250 \
   --minsup 25 50 100 \
   --memory-limit-rows 1 7 25 100
```

The 12 selected dimensions were tested in all 12 configurations. Every run
reported `PASS`: the cell counts matched, cells only in either implementation
were 0, support mismatches were 0, and maximum absolute support difference was
0. For example, at `minsup=25`, both implementations returned 4,829 cells for
each memory budget.