# PostgreSQL Schema Diff and Safe Migration Tool

A small Python tool that compares two PostgreSQL databases and shows you exactly how they differ. It can then update your **old** database so its structure matches your **new** one, with several safety nets so you don't lose data.

Think of it like "track changes" for a database structure.

---

## What it does,

1. Connects to two databases: the **old** one (the one you want to update) and the **new** one (the one you want to match).
2. Reads the structure of both: tables, columns, constraints (primary keys, foreign keys, unique, check) and indexes.
3. Compares them and lists every difference.
4. Writes reports you can read and share (HTML and JSON).
5. Writes a migration SQL file, which is the set of commands that would make the old database match the new one.
6. Asks you whether to apply the changes. Nothing is changed unless you type `yes`.

**It only changes structure, not data.** The one exception is when you approve dropping a table or column, and even then the data is backed up first (see "Safety features").

---

## Before you start

You need:

- **Python 3.10 or newer**
- **Two PostgreSQL databases** you can connect to
- A database user with permission to read the schema, and (if you want to apply changes) permission to alter the old database

### Install

```bash
pip install psycopg2-binary python-dotenv
```

If you keep a `requirements.txt`, it only needs these two lines:

```
psycopg2-binary
python-dotenv
```

---

## Setup

The tool never has passwords or hostnames written inside the code. Everything comes from a file called `.env` in the same folder as the script.

Create a file named `.env` like this and fill in your real values:

```env
# ---- OLD database (the one that will be updated) ----
OLD_DB_HOST=localhost
OLD_DB_PORT=5432
OLD_DB_NAME=my_old_db
OLD_DB_USER=postgres
OLD_DB_PASSWORD=your_password_here

# ---- NEW database (the reference to match) ----
NEW_DB_HOST=localhost
NEW_DB_PORT=5432
NEW_DB_NAME=my_new_db
NEW_DB_USER=postgres
NEW_DB_PASSWORD=your_password_here

# ---- Optional settings (defaults shown) ----
PG_SCHEMA=public
REPORTS_DIR=reports
JSON_REPORT_NAME=schema_diff.json
HTML_REPORT_NAME=schema_diff.html
SQL_REPORT_NAME=migration.sql
ARCHIVE_SCHEMA=schema_diff_archive
```

| Setting | Required? | What it means |
|---|---|---|
| `OLD_DB_*` | Yes | Connection details for the database that will be updated. Port defaults to 5432. |
| `NEW_DB_*` | Yes | Connection details for the database you want to match. Port defaults to 5432. |
| `PG_SCHEMA` | No | Which schema to compare. Default is `public`. |
| `REPORTS_DIR` | No | Folder where reports are saved. Default is `reports`. |
| `JSON_REPORT_NAME`, `HTML_REPORT_NAME`, `SQL_REPORT_NAME` | No | File names for the reports. |
| `ARCHIVE_SCHEMA` | No | Name of the schema where backups of dropped data are stored. Default is `schema_diff_archive`. |

> **Important:** Add `.env` to your `.gitignore` so your passwords never get uploaded to GitHub. Share a `.env.example` file with fake values instead.

---

## How to run it

```bash
python schema_diff.py
```

You will see progress messages, then a summary of the differences, then the list of SQL statements that would run. Finally the tool asks:

```
Apply N change(s) to OLD database 'my_old_db'@localhost? (yes/no):
```

- Type `yes` (or `y`) to continue.
- Type anything else to stop. Nothing is changed, and you still get all the reports.

If the plan includes dropping tables or columns, you get a **second, separate question** just for those. You can approve the safe changes and still say no to the destructive ones.

---

## What files it creates

All files go into the `reports` folder (or whatever you set in `REPORTS_DIR`).

| File | What it is |
|---|---|
| `schema_diff.json` | The full list of differences in machine-readable form. |
| `schema_diff.html` | The same differences as a colour-coded table. Green is added, red is removed, yellow is changed. Open it in any browser. |
| `migration_<timestamp>.sql` | The SQL that would make the old database match the new one. Read it before you apply anything. |
| `final_report_<timestamp>.html` | A report of what actually happened in this run (see below). |
| `final_report_<timestamp>.json` | The same final report in JSON form. |

### What the final report tells you

- **Status:** one of `APPLIED`, `APPLIED WITH SKIPPED ITEMS`, `NOT APPLIED`, `FAILED - ROLLED BACK`, or `IN SYNC`.
- **Done:** every statement that was applied.
- **Skipped for data safety:** changes the tool refused to make, with the reason.
- **Not applied:** changes that were not run because you said no, or because of an error.
- **Remaining differences:** anything still different between the two databases after the run.
- **Data protection:** which backup tables were created, and row counts for every table before and after.

---

## What kinds of changes it handles

| Change | Safe or destructive? |
|---|---|
| New table | Safe |
| New column | Safe |
| Changed column (type, NOT NULL, default) | Safe, with checks (see below) |
| New, changed, or removed constraint | Safe, with checks |
| New, changed, or removed index | Safe |
| Missing sequences for auto-numbered columns | Safe, created automatically |
| **Dropped table** | **Destructive**, needs a separate confirmation |
| **Dropped column** | **Destructive**, needs a separate confirmation |

---

## Safety features

This is the most important part of the tool, so here it is in simple terms.

**1. You always see the plan first.** Every SQL statement is printed and saved to a file before anything runs.

**2. Nothing happens without a yes.** The tool asks before touching your database, and asks again before any destructive step.

**3. Pre-flight checks.** Before running, the tool looks at your existing data and removes any change that would fail or reject it:
- Making a column `NOT NULL` when it already contains empty values.
- Adding a primary key or unique constraint when duplicate values already exist.

These changes are skipped, and the final report tells you why and how many rows are the problem, so you can clean the data and run again.

**4. Backup before dropping.** If you approve dropping a table or column, the whole affected table is first copied into the archive schema (default `schema_diff_archive`) with a timestamp in its name. If you change your mind later, the data is still there.

**5. One transaction.** All statements run together as a single all-or-nothing unit. If any one fails, everything is rolled back and the old database is left exactly as it was.

**6. Row count check.** Right before the final commit, the tool compares the number of rows in every surviving table against what it was before. If any table has fewer rows, the whole thing is rolled back.

**7. Verification.** After a successful run, the tool compares the databases again and reports anything that is still different.

---

## A typical run, step by step

1. Fill in `.env`.
2. Run `python schema_diff.py`.
3. Read the summary in the terminal.
4. Open `reports/schema_diff.html` in your browser to review the differences.
5. Open the `migration_<timestamp>.sql` file if you want to read the exact SQL.
6. Answer `yes` to apply the safe changes.
7. Answer `yes` or `no` to the destructive changes.
8. Open the final report to confirm what happened.

---

## Good habits (please read)

- **Try it on a copy first.** Restore a backup of your old database somewhere else and run the tool there before using it on anything important.
- **Take your own backup too.** The tool protects against dropped data, but a normal `pg_dump` is still a good idea before any migration.
- **Read the SQL file.** It takes two minutes and can save you a bad day.
- **Watch out for renames.** If you renamed a column or table in the new database, the tool sees it as "old one removed, new one added". Approving that would drop the old column or table, so check that carefully. The backup will have the data, but the new column will start empty.
- **Archive tables can be large.** The backup is a full copy of each affected table, so make sure you have enough disk space.

---

## Limitations

The tool is focused on the basics. It does **not** currently compare or migrate:

- Views, materialized views, functions, procedures, or triggers
- Enum types and other custom types (only used as column types)
- Permissions, ownership, or comments
- Column order
- More than one schema per run (set `PG_SCHEMA` and run again for another)

It also does not copy any data between the two databases. It only changes structure.

Changing a column's type uses a cast (`USING column::new_type`). If existing values cannot be converted, the statement fails and everything is rolled back safely.

---

## Troubleshooting

| Problem | What to try |
|---|---|
| `Missing required environment variable: OLD_DB_HOST` | Your `.env` file is missing, in the wrong folder, or a required line is empty. |
| Connection refused or timeout | Check host, port, firewall, and that PostgreSQL is running. |
| Password authentication failed | Check the user and password in `.env`. |
| `permission denied` while applying | The database user needs rights to alter tables in the old database. |
| `FAILED - ROLLED BACK` status | Nothing was changed. Read the error in the final report, fix the cause, and run again. |
| A change shows under "Skipped" | Existing data conflicts with it. Clean the data, then run again. |
| `TypeError` about `str | None` | You are on Python older than 3.10. Upgrade Python. |

---

## Project layout

```
.
├── schema_diff.py        # the tool
├── .env                  # your private settings (do not commit)
├── .env.example          # sample settings (safe to commit)
├── requirements.txt      # psycopg2-binary, python-dotenv
├── README.md             # this file
└── reports/              # generated reports appear here
```

---

## Built with

- Python
- PostgreSQL
- `psycopg2` for database access
- `python-dotenv` for reading settings from `.env`
