# data-engineering-lab

Data engineering concepts as small, runnable, tested Python projects: how data
actually gets written, moved and transformed, from the operating system up to
pipelines, SQL, Spark, Airflow, dbt and the cloud.

Each folder is self-contained, with its own README, code and tests.

## Projects

Larger end-to-end builds live in their own repositories so they can have their own
deployment, CI and roadmap:

| Project | What it is | Stack |
|---------|------------|-------|
| [garmin-health-lakehouse](https://github.com/ajesqueda/garmin-health-lakehouse) | Bronze → silver → gold lakehouse over my Garmin Connect health data, refreshed daily at 6 AM; gold feeds a future recovery-score model | Databricks Free Edition, Lakeflow declarative pipelines, Auto Loader, Unity Catalog, Asset Bundles, PySpark |

## Index

| Topic | What it shows | Source |
|-------|---------------|--------|
| [Atomic file writes](atomic-file-writes/) | Crash-safe output files with the POSIX API: temp file + `fsync` + `rename`, and why in-place overwrites tear | CX651 Week 7 |

## Run it

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

## Workflow

Work happens on `feat/*` branches off `dev`, then is promoted `dev` → `qa` → `main`
through pull requests. CI runs ruff and pytest on every PR.
