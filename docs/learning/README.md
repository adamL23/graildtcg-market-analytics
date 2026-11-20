# Building an End-to-End Data Pipeline with Python, PostgreSQL, REST APIs and Power BI: The GraildTCG Case Study

This learning guide explains the implemented GraildTCG Phase 1 pipeline from
first principles. It is both a tutorial for readers with basic Python and SQL
knowledge and a technical map of the real repository.

### Prerequisites

- Comfort reading basic Python functions, classes, loops, and exceptions.
- Familiarity with `SELECT`, `INSERT`, `UPDATE`, and `JOIN` in SQL.
- Windows PowerShell, PostgreSQL, and VS Code installed for the hands-on work.
- No previous production data-engineering experience is assumed.

### Recommended learning order

Read Chapters 1–5 in order, then study Chapters 6–9 together while opening the
referenced source files. Chapters 10–12 explain reporting and operations.
Chapter 13 is a reproducible standalone build exercise. Chapter 14 separates
completed Phase 1 work from future improvements. Chapter 15 traces one real
record end to end, and Chapter 16 contains exercise solutions.

### Table of contents

1. [Learning roadmap and source audit](00_LEARNING_ROADMAP.md)
2. [Data engineering foundations](01_DATA_ENGINEERING_FOUNDATIONS.md)
3. [System architecture](02_SYSTEM_ARCHITECTURE.md)
4. [Environment setup](03_ENVIRONMENT_SETUP.md)
5. [Database design and SQL](04_DATABASE_AND_SQL.md)
6. [APIs and JSON](05_API_AND_JSON.md)
7. [Python codebase walkthrough](06_PYTHON_CODEBASE_WALKTHROUGH.md)
8. [ETL pipelines](07_ETL_PIPELINES.md)
9. [Data quality and reliability](08_DATA_QUALITY_AND_RELIABILITY.md)
10. [SQL verification and testing](09_SQL_VERIFICATION_AND_TESTING.md)
11. [Power BI reporting](10_POWER_BI_REPORTING.md)
12. [Challenges and tradeoffs](11_CHALLENGES_AND_TRADEOFFS.md)
13. [Pipeline operations](12_PIPELINE_OPERATIONS.md)
14. [Build your own pipeline](13_BUILD_YOUR_OWN_PIPELINE.md)
15. [Future improvements](14_FUTURE_IMPROVEMENTS.md)
16. [End-to-end worked example](15_END_TO_END_WORKED_EXAMPLE.md)
17. [Exercise answer key](16_EXERCISE_ANSWER_KEY.md)
18. [Second-pass change summary](SECOND_PASS_CHANGE_SUMMARY.md)

### How to read repository references

Paths such as `src/gmad/history_ingest.py::load_history` name an actual source
file and function. Short excerpts are copied from the implementation; ellipses
mean unrelated lines were removed. Blocks labeled **Teaching example** are
simplified code and are not part of GraildTCG.

All commands assume the repository root is the current directory. Never place a
real password or API key in this guide, Git, screenshots, or console output.

