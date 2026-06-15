# Best Practice: Data Pipelines & ETL

Patterns for **data extraction, transformation, loading, and validation** workflows.

---

## Recommended Structures

| Scenario | Structure | Why |
|----------|-----------|-----|
| Simple one-shot script (< 1 min) | Single `simple` task | No decomposition needed. |
| Multi-stage pipeline (extract → transform → load) | `nested` with per-stage subtasks | Each stage has different failure modes; isolation enables targeted retry. |
| Long-running data processing (> 1 min) | Use `long_running` for the processing step | Prevents session timeout. |
| Pipeline with expensive setup (DB init, data download) | Top-level `simple` or `long_running` setup task + `nested` processing task | Setup runs first as a standalone task; processing can retry independently. |

---

## Patterns

### Pattern 1: File-based state passing between stages

Pipeline stages are context-isolated — they share the filesystem only. Each stage should read its input from a file and write its output to a file. Be explicit about paths in `initial_hint`.

```yaml
- id: 1
  name: "Process and validate customer data"
  type: nested
  completion_criteria: |
    1. output/customers_clean.csv exists with no validation errors
    2. output/validation_report.txt shows 0 errors
  subtasks:
    - id: 1.1
      name: "Extract and normalize raw data"
      type: simple
      completion_criteria: |
        1. output/customers_raw.csv created from source database
        2. Column names normalized to snake_case
        3. Row count logged to output/extract_log.txt
      initial_hint: |
        Source: postgresql://localhost/prod (read-only)
        Query: SELECT * FROM customers WHERE updated_at > '2024-01-01'
        Write output to output/customers_raw.csv
        Log row count to output/extract_log.txt

    - id: 1.2
      name: "Clean and transform data"
      type: simple
      completion_criteria: |
        1. output/customers_clean.csv created
        2. Duplicates removed, emails validated, phone numbers formatted
        3. Transform summary written to output/transform_log.txt
      initial_hint: |
        Input: output/customers_raw.csv
        Output: output/customers_clean.csv
        Rules:
        - Remove duplicate rows (by customer_id)
        - Validate email format (drop invalid rows, log them)
        - Format phone to E.164

    - id: 1.3
      name: "Validate final output"
      type: simple
      max_attempts: 1
      model: lite
      system_prompt_prefix: |
        You are a data validator. Do NOT modify any data files.
      completion_criteria: |
        1. output/validation_report.txt created with check results
        2. All checks pass: no nulls in required fields, row count matches expected range
      initial_hint: |
        Input: output/customers_clean.csv
        Checks:
        - No null values in: customer_id, email, name
        - Row count within 10% of extract_log.txt count
        - All emails match format: *@*.*
        Write results to output/validation_report.txt
```

### Pattern 2: Expensive setup as a top-level task

When the pipeline requires a one-time expensive setup (downloading a large dataset, building a Docker image, initializing a database), make it a **top-level task** before the processing task. This avoids re-running setup on retry.

```yaml
subtasks:
  - id: 1.1
    name: "Download source dataset"
    type: long_running_once
    completion_criteria: |
      1. data/raw/dataset.parquet exists
      2. File size > 100MB (sanity check)
    initial_hint: |
      Download from: https://data.example.com/export/latest.parquet
      Save to: data/raw/dataset.parquet
      This is a large file (~100MB+).

- id: 2
  name: "Process dataset"
  type: simple
  completion_criteria: |
    1. data/processed/output.csv created
  initial_hint: |
    Input: data/raw/dataset.parquet (already downloaded by previous step)
```

### Pattern 3: Validate input data before processing

When the pipeline involves expensive processing, add a lightweight validation step upfront to catch data issues early — missing files, wrong schema, empty datasets — before wasting time on processing that's doomed to fail.

```yaml
subtasks:
  - id: 1.1
    name: "Validate input data"
    type: simple
    max_attempts: 1
    model: lite
    system_prompt_prefix: |
      You are a data validator. Do NOT modify any data files.
    completion_criteria: |
      1. input_validation.txt confirms all checks passed
    initial_hint: |
      Validate before processing:
      - data/raw/input.csv exists and is non-empty
      - Has expected columns: customer_id, email, name, created_at
      - Row count > 0
      - No obvious corruption (parseable as CSV)
      Write results to input_validation.txt.
      If any check fails, report clearly — do NOT proceed.

  - id: 1.2
    name: "Process and transform data"
    type: simple
    completion_criteria: |
      1. output/processed.csv created
    initial_hint: |
      Read input_validation.txt to confirm input is valid.
      Input: data/raw/input.csv
      Output: output/processed.csv
```

### Pattern 4: Partial success handling

Data pipelines often encounter partial failures (some records fail validation, some API calls timeout). Design `completion_criteria` to handle this explicitly rather than treating any error as total failure.

```yaml
completion_criteria: |
  1. At least 95% of records processed successfully
  2. Failed records logged to output/failures.csv with error reason
  3. Summary statistics written to output/pipeline_summary.txt

initial_hint: |
  Not all records will be clean — that's expected.
  For each record that fails validation:
  - Log it to output/failures.csv (record_id, error_reason)
  - Continue processing remaining records
  Do NOT stop the pipeline on individual record failures.
```

### Pattern 5: Long-running data processing

For heavy data processing (large file transforms, ML inference, batch API calls), use `long_running` to avoid session timeout.

```yaml
- id: 1.2
  name: "Run batch inference on dataset"
  type: long_running
  completion_criteria: |
    1. output/predictions.csv exists with predictions for all input rows
    2. Exit code 0
  initial_hint: |
    Run: python scripts/batch_inference.py --input data/processed/input.csv --output output/predictions.csv
    This processes ~100k records and may take 10+ minutes.
```

---

## Anti-Patterns

| Anti-pattern | Problem | Better |
|--------------|---------|--------|
| All pipeline stages in one `simple` task | If the last stage fails, the entire pipeline reruns including expensive extraction | Use `nested` to isolate stages |
| No explicit input/output file paths | AI guesses paths, later stages can't find files | Always specify exact paths in `initial_hint` |
| Treating any record failure as task failure | Pipeline aborts on first bad record | Use partial success criteria (e.g., "95% processed") |
| Re-downloading data on every retry | Wastes time and bandwidth | Make data download a top-level `long_running` task before the processing pipeline |
