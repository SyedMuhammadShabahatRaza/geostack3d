# geostack3d Test Suite

## Setup

Install test dependencies (from the repo root):

```cmd
pip install -e .[dev]
```

This uses the `dev` optional-dependencies group already defined in `pyproject.toml`
(`pytest`, `pytest-cov`).

## Running the tests

From the repo root:

```cmd
pytest
```

This will use the `[tool.pytest.ini_options]` settings already in `pyproject.toml`
(`testpaths = ["tests"]`), so it automatically finds everything in this folder.

To see a coverage report:

```cmd
pytest --cov=geostack3d --cov-report=term-missing
```

## What's covered

| File | What it tests |
|---|---|
| `test_config.py` | The two `PipelineConfig` validators (must have a source, must have a study area), and stage config defaults |
| `test_geometry.py` | Valid data passes untouched; a deliberately broken bowtie polygon gets repaired; null geometries get dropped; `auto_repair=False` raises instead of silently fixing |
| `test_crs.py` | Already-correct CRS is skipped unchanged; mismatched CRS gets genuinely reprojected; missing CRS raises |
| `test_schema.py` | `field_map` renames correctly; `drop_extra_fields` keeps only canonical fields + geometry; geometry column is never dropped; missing canonical fields get created as `None` |
| `test_qa.py` | Each of the 5 checks (row count, required fields, geometry validity, null geometry, CRS match) individually; `halt_on_failure` True vs. False behavior |
| `test_validate.py` | Missing required source raises; missing optional source is skipped; missing study area always raises |

## Notes

- All tests use small, synthetic data built in-memory via fixtures in `conftest.py` — no
  dependency on the real dataset2 files, so tests run in seconds and are fully
  reproducible on any machine.
- These tests were written based on the documented, verified behavior of each module.
  **Run them locally and confirm all pass before considering this complete** — some
  edge cases (exact error message wording, specific exception types) may need small
  adjustments to match your exact current code.
