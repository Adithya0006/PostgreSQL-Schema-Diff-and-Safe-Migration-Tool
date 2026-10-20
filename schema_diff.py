# """
# schema_diff.py

# Compares the schema (tables, columns, constraints, indexes) of two
# PostgreSQL databases ("old" and "new") and produces:

#   - reports/schema_diff.json  -> machine-readable diff
#   - reports/schema_diff.html  -> human-readable diff report

# All connection details and settings are read from a `.env` file
# (see `.env.example`). Nothing is hard-coded in this file.

# Usage:
#     pip install -r requirements.txt
#     cp .env.example .env   # then edit .env with your real values
#     python schema_diff.py
# """

# import html
# import json
# import os
# from pathlib import Path

# import psycopg2
# import psycopg2.extras
# from dotenv import load_dotenv

# # --------------------------------------------------------------------------
# # 0. Configuration (all values come from environment / .env, nothing hard-coded)
# # --------------------------------------------------------------------------

# load_dotenv()


# def _require_env(name: str, default: str | None = None) -> str:
#     value = os.getenv(name, default)
#     if value is None or value == "":
#         raise RuntimeError(
#             f"Missing required environment variable: {name}. "
#             f"Check your .env file (see .env.example)."
#         )
#     return value


# OLD_DB = {
#     "host": _require_env("OLD_DB_HOST"),
#     "port": _require_env("OLD_DB_PORT", "5432"),
#     "dbname": _require_env("OLD_DB_NAME"),
#     "user": _require_env("OLD_DB_USER"),
#     "password": _require_env("OLD_DB_PASSWORD"),
# }

# NEW_DB = {
#     "host": _require_env("NEW_DB_HOST"),
#     "port": _require_env("NEW_DB_PORT", "5432"),
#     "dbname": _require_env("NEW_DB_NAME"),
#     "user": _require_env("NEW_DB_USER"),
#     "password": _require_env("NEW_DB_PASSWORD"),
# }

# SCHEMA_NAME = os.getenv("PG_SCHEMA", "public")
# REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
# JSON_REPORT_PATH = REPORTS_DIR / os.getenv("JSON_REPORT_NAME", "schema_diff.json")
# HTML_REPORT_PATH = REPORTS_DIR / os.getenv("HTML_REPORT_NAME", "schema_diff.html")


# # --------------------------------------------------------------------------
# # 1. Connection helper
# # --------------------------------------------------------------------------

# def get_connection(config: dict):
#     return psycopg2.connect(
#         host=config["host"],
#         port=config["port"],
#         dbname=config["dbname"],
#         user=config["user"],
#         password=config["password"],
#     )


# # --------------------------------------------------------------------------
# # 2. Schema extraction
# # --------------------------------------------------------------------------

# def get_schema(conn, schema_name: str) -> dict:
#     """
#     Returns a dict describing every table in `schema_name`:

#     {
#         "table_name": {
#             "columns": {
#                 "col_name": {
#                     "type": "character varying",
#                     "length": 50,
#                     "nullable": "YES"/"NO",
#                     "default": "..." or None,
#                 }
#             },
#             "constraints": {
#                 "constraint_name": {
#                     "type": "PRIMARY KEY" / "FOREIGN KEY" / "UNIQUE" / "CHECK",
#                     "columns": ["col1", "col2"],
#                     "foreign_table": "other_table" or None,
#                     "foreign_columns": ["col"] or [],
#                 }
#             },
#             "indexes": {
#                 "index_name": "CREATE INDEX ... definition"
#             },
#         }
#     }
#     """
#     cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
#     schema: dict = {}

#     # ---- Tables ----
#     cur.execute(
#         """
#         SELECT table_name
#         FROM information_schema.tables
#         WHERE table_schema = %s AND table_type = 'BASE TABLE'
#         ORDER BY table_name
#         """,
#         (schema_name,),
#     )
#     for row in cur.fetchall():
#         schema[row["table_name"]] = {
#             "columns": {},
#             "constraints": {},
#             "indexes": {},
#         }

#     # ---- Columns ----
#     cur.execute(
#         """
#         SELECT table_name, column_name, data_type,
#                character_maximum_length, is_nullable, column_default
#         FROM information_schema.columns
#         WHERE table_schema = %s
#         ORDER BY table_name, ordinal_position
#         """,
#         (schema_name,),
#     )
#     for row in cur.fetchall():
#         table = schema.get(row["table_name"])
#         if table is None:
#             continue
#         table["columns"][row["column_name"]] = {
#             "type": row["data_type"],
#             "length": row["character_maximum_length"],
#             "nullable": row["is_nullable"],
#             "default": row["column_default"],
#         }

#     # ---- Constraints (PK, FK, UNIQUE, CHECK) ----
#     cur.execute(
#         """
#         SELECT
#             tc.constraint_name,
#             tc.constraint_type,
#             tc.table_name,
#             kcu.column_name,
#             ccu.table_name  AS foreign_table,
#             ccu.column_name AS foreign_column
#         FROM information_schema.table_constraints tc
#         JOIN information_schema.key_column_usage kcu
#             ON tc.constraint_name = kcu.constraint_name
#             AND tc.table_schema = kcu.table_schema
#         LEFT JOIN information_schema.constraint_column_usage ccu
#             ON tc.constraint_name = ccu.constraint_name
#             AND tc.constraint_type = 'FOREIGN KEY'
#             AND tc.table_schema = ccu.table_schema
#         WHERE tc.table_schema = %s
#         ORDER BY tc.table_name, tc.constraint_name
#         """,
#         (schema_name,),
#     )
#     for row in cur.fetchall():
#         table = schema.get(row["table_name"])
#         if table is None:
#             continue
#         entry = table["constraints"].setdefault(
#             row["constraint_name"],
#             {
#                 "type": row["constraint_type"],
#                 "columns": [],
#                 "foreign_table": row["foreign_table"],
#                 "foreign_columns": [],
#             },
#         )
#         if row["column_name"] and row["column_name"] not in entry["columns"]:
#             entry["columns"].append(row["column_name"])
#         if row["foreign_column"] and row["foreign_column"] not in entry["foreign_columns"]:
#             entry["foreign_columns"].append(row["foreign_column"])

#     # ---- Indexes ----
#     cur.execute(
#         """
#         SELECT indexname, tablename, indexdef
#         FROM pg_indexes
#         WHERE schemaname = %s
#         ORDER BY tablename, indexname
#         """,
#         (schema_name,),
#     )
#     for row in cur.fetchall():
#         table = schema.get(row["tablename"])
#         if table is None:
#             continue
#         table["indexes"][row["indexname"]] = row["indexdef"]

#     cur.close()
#     return schema


# # --------------------------------------------------------------------------
# # 3. Comparison
# # --------------------------------------------------------------------------

# def compare_schemas(old_schema: dict, new_schema: dict) -> dict:
#     changes = []

#     old_tables = set(old_schema.keys())
#     new_tables = set(new_schema.keys())

#     for table in sorted(new_tables - old_tables):
#         changes.append({"type": "TABLE_ADDED", "table": table})

#     for table in sorted(old_tables - new_tables):
#         changes.append({"type": "TABLE_REMOVED", "table": table})

#     for table in sorted(old_tables & new_tables):
#         old_t = old_schema[table]
#         new_t = new_schema[table]

#         # --- Columns ---
#         old_cols = set(old_t["columns"].keys())
#         new_cols = set(new_t["columns"].keys())

#         for col in sorted(new_cols - old_cols):
#             changes.append({"type": "COLUMN_ADDED", "table": table, "column": col})

#         for col in sorted(old_cols - new_cols):
#             changes.append({"type": "COLUMN_REMOVED", "table": table, "column": col})

#         for col in sorted(old_cols & new_cols):
#             old_def = old_t["columns"][col]
#             new_def = new_t["columns"][col]
#             if old_def != new_def:
#                 changes.append(
#                     {
#                         "type": "COLUMN_CHANGED",
#                         "table": table,
#                         "column": col,
#                         "old": old_def,
#                         "new": new_def,
#                     }
#                 )

#         # --- Constraints ---
#         old_cons = set(old_t["constraints"].keys())
#         new_cons = set(new_t["constraints"].keys())

#         for name in sorted(new_cons - old_cons):
#             changes.append(
#                 {
#                     "type": "CONSTRAINT_ADDED",
#                     "table": table,
#                     "name": name,
#                     "new": new_t["constraints"][name],
#                 }
#             )

#         for name in sorted(old_cons - new_cons):
#             changes.append(
#                 {
#                     "type": "CONSTRAINT_REMOVED",
#                     "table": table,
#                     "name": name,
#                     "old": old_t["constraints"][name],
#                 }
#             )

#         for name in sorted(old_cons & new_cons):
#             old_def = old_t["constraints"][name]
#             new_def = new_t["constraints"][name]
#             if old_def != new_def:
#                 changes.append(
#                     {
#                         "type": "CONSTRAINT_CHANGED",
#                         "table": table,
#                         "name": name,
#                         "old": old_def,
#                         "new": new_def,
#                     }
#                 )

#         # --- Indexes ---
#         old_idx = set(old_t["indexes"].keys())
#         new_idx = set(new_t["indexes"].keys())

#         for name in sorted(new_idx - old_idx):
#             changes.append(
#                 {
#                     "type": "INDEX_ADDED",
#                     "table": table,
#                     "name": name,
#                     "new": new_t["indexes"][name],
#                 }
#             )

#         for name in sorted(old_idx - new_idx):
#             changes.append(
#                 {
#                     "type": "INDEX_REMOVED",
#                     "table": table,
#                     "name": name,
#                     "old": old_t["indexes"][name],
#                 }
#             )

#         for name in sorted(old_idx & new_idx):
#             if old_t["indexes"][name] != new_t["indexes"][name]:
#                 changes.append(
#                     {
#                         "type": "INDEX_CHANGED",
#                         "table": table,
#                         "name": name,
#                         "old": old_t["indexes"][name],
#                         "new": new_t["indexes"][name],
#                     }
#                 )

#     summary: dict = {}
#     for change in changes:
#         summary[change["type"]] = summary.get(change["type"], 0) + 1

#     return {
#         "summary": summary,
#         "changes": changes,
#     }


# # --------------------------------------------------------------------------
# # 4. Report generation
# # --------------------------------------------------------------------------

# def write_json_report(report: dict, path: Path) -> None:
#     path.parent.mkdir(parents=True, exist_ok=True)
#     path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


# def generate_html_report(report: dict, path: Path, old_label: str, new_label: str) -> None:
#     rows = []

#     for change in report["changes"]:
#         change_type = change["type"]

#         if "ADDED" in change_type:
#             color = "#dcfce7"
#         elif "REMOVED" in change_type:
#             color = "#fee2e2"
#         else:
#             color = "#fef3c7"

#         rows.append(
#             f"""
#             <tr style="background:{color}">
#                 <td>{html.escape(change_type)}</td>
#                 <td>{html.escape(change.get("table", ""))}</td>
#                 <td>{html.escape(change.get("column", change.get("name", "")))}</td>
#                 <td><pre>{html.escape(str(change.get("old", "")))}</pre></td>
#                 <td><pre>{html.escape(str(change.get("new", "")))}</pre></td>
#             </tr>
#             """
#         )

#     summary = "".join(
#         f"<li>{html.escape(k)}: {v}</li>" for k, v in report["summary"].items()
#     )

#     page = f"""
# <!DOCTYPE html>
# <html>
# <head>
#     <meta charset="utf-8">
#     <title>PostgreSQL Schema Diff</title>
#     <style>
#         body {{
#             font-family: Arial, sans-serif;
#             margin: 30px;
#         }}
#         table {{
#             border-collapse: collapse;
#             width: 100%;
#         }}
#         th, td {{
#             border: 1px solid #ddd;
#             padding: 10px;
#             text-align: left;
#             vertical-align: top;
#         }}
#         th {{
#             background: #1f2937;
#             color: white;
#         }}
#         pre {{
#             white-space: pre-wrap;
#             max-width: 350px;
#         }}
#     </style>
# </head>
# <body>
#     <h1>PostgreSQL Schema Comparison</h1>
#     <p>Old: {html.escape(old_label)} | New: {html.escape(new_label)}</p>

#     <h2>Summary</h2>
#     <ul>{summary}</ul>

#     <h2>Detailed Changes</h2>
#     <table>
#         <tr>
#             <th>Change</th>
#             <th>Table</th>
#             <th>Column / Object</th>
#             <th>Old Definition</th>
#             <th>New Definition</th>
#         </tr>
#         {''.join(rows)}
#     </table>
# </body>
# </html>
# """
#     path.parent.mkdir(parents=True, exist_ok=True)
#     path.write_text(page, encoding="utf-8")


# # --------------------------------------------------------------------------
# # 5. Main
# # --------------------------------------------------------------------------

# def main() -> None:
#     print(f"Connecting to old database: {OLD_DB['dbname']}@{OLD_DB['host']}")
#     old_conn = get_connection(OLD_DB)

#     print(f"Connecting to new database: {NEW_DB['dbname']}@{NEW_DB['host']}")
#     new_conn = get_connection(NEW_DB)

#     try:
#         print(f"Reading schema '{SCHEMA_NAME}' from old database...")
#         old_schema = get_schema(old_conn, SCHEMA_NAME)

#         print(f"Reading schema '{SCHEMA_NAME}' from new database...")
#         new_schema = get_schema(new_conn, SCHEMA_NAME)
#     finally:
#         old_conn.close()
#         new_conn.close()

#     print("Comparing schemas...")
#     report = compare_schemas(old_schema, new_schema)

#     write_json_report(report, JSON_REPORT_PATH)
#     print(f"JSON report written to {JSON_REPORT_PATH}")

#     generate_html_report(
#         report,
#         HTML_REPORT_PATH,
#         old_label=OLD_DB["dbname"],
#         new_label=NEW_DB["dbname"],
#     )
#     print(f"HTML report written to {HTML_REPORT_PATH}")

#     print("\nSummary:")
#     for change_type, count in report["summary"].items():
#         print(f"  {change_type}: {count}")

#     if not report["changes"]:
#         print("No schema differences found.")


# if __name__ == "__main__":
#     main()
























# """
# schema_diff.py

# Compares the schema (tables, columns, constraints, indexes) of two
# PostgreSQL databases ("old" and "new") and produces:

#   - reports/schema_diff.json  -> machine-readable diff
#   - reports/schema_diff.html  -> human-readable diff report
#   - reports/migration.sql     -> SQL that would make "old" match "new"

# After the report, you are asked whether to APPLY the changes to the old
# database. Answer "yes" to proceed; anything else exits without changes.
# Destructive changes (dropping tables/columns) need a separate confirmation.

# All connection details and settings are read from a `.env` file
# (see `.env.example`). Nothing is hard-coded in this file.

# Usage:
#     pip install -r requirements.txt
#     cp .env.example .env   # then edit .env with your real values
#     python schema_diff.py
# """

# import html
# import json
# import os
# import re
# from pathlib import Path

# import psycopg2
# import psycopg2.extras
# from dotenv import load_dotenv

# # --------------------------------------------------------------------------
# # 0. Configuration (all values come from environment / .env, nothing hard-coded)
# # --------------------------------------------------------------------------

# load_dotenv()


# def _require_env(name: str, default: str | None = None) -> str:
#     value = os.getenv(name, default)
#     if value is None or value == "":
#         raise RuntimeError(
#             f"Missing required environment variable: {name}. "
#             f"Check your .env file (see .env.example)."
#         )
#     return value


# OLD_DB = {
#     "host": _require_env("OLD_DB_HOST"),
#     "port": _require_env("OLD_DB_PORT", "5432"),
#     "dbname": _require_env("OLD_DB_NAME"),
#     "user": _require_env("OLD_DB_USER"),
#     "password": _require_env("OLD_DB_PASSWORD"),
# }

# NEW_DB = {
#     "host": _require_env("NEW_DB_HOST"),
#     "port": _require_env("NEW_DB_PORT", "5432"),
#     "dbname": _require_env("NEW_DB_NAME"),
#     "user": _require_env("NEW_DB_USER"),
#     "password": _require_env("NEW_DB_PASSWORD"),
# }

# SCHEMA_NAME = os.getenv("PG_SCHEMA", "public")
# REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
# JSON_REPORT_PATH = REPORTS_DIR / os.getenv("JSON_REPORT_NAME", "schema_diff.json")
# HTML_REPORT_PATH = REPORTS_DIR / os.getenv("HTML_REPORT_NAME", "schema_diff.html")
# SQL_REPORT_PATH = REPORTS_DIR / os.getenv("SQL_REPORT_NAME", "migration.sql")


# # --------------------------------------------------------------------------
# # 1. Connection helper
# # --------------------------------------------------------------------------

# def get_connection(config: dict):
#     return psycopg2.connect(
#         host=config["host"],
#         port=config["port"],
#         dbname=config["dbname"],
#         user=config["user"],
#         password=config["password"],
#     )


# # --------------------------------------------------------------------------
# # 2. Schema extraction
# # --------------------------------------------------------------------------

# def get_schema(conn, schema_name: str) -> dict:
#     """
#     Returns a dict describing every table in `schema_name`:

#     {
#         "table_name": {
#             "columns": {
#                 "col_name": {
#                     "type": "character varying",
#                     "length": 50,
#                     "nullable": "YES"/"NO",
#                     "default": "..." or None,
#                 }
#             },
#             "constraints": {
#                 "constraint_name": {
#                     "type": "PRIMARY KEY" / "FOREIGN KEY" / "UNIQUE" / "CHECK",
#                     "columns": ["col1", "col2"],
#                     "foreign_table": "other_table" or None,
#                     "foreign_columns": ["col"] or [],
#                 }
#             },
#             "indexes": {
#                 "index_name": "CREATE INDEX ... definition"
#             },
#         }
#     }
#     """
#     cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
#     schema: dict = {}

#     # ---- Tables ----
#     cur.execute(
#         """
#         SELECT table_name
#         FROM information_schema.tables
#         WHERE table_schema = %s AND table_type = 'BASE TABLE'
#         ORDER BY table_name
#         """,
#         (schema_name,),
#     )
#     for row in cur.fetchall():
#         schema[row["table_name"]] = {
#             "columns": {},
#             "constraints": {},
#             "indexes": {},
#         }

#     # ---- Columns ----
#     cur.execute(
#         """
#         SELECT table_name, column_name, data_type,
#                character_maximum_length, is_nullable, column_default
#         FROM information_schema.columns
#         WHERE table_schema = %s
#         ORDER BY table_name, ordinal_position
#         """,
#         (schema_name,),
#     )
#     for row in cur.fetchall():
#         table = schema.get(row["table_name"])
#         if table is None:
#             continue
#         table["columns"][row["column_name"]] = {
#             "type": row["data_type"],
#             "length": row["character_maximum_length"],
#             "nullable": row["is_nullable"],
#             "default": row["column_default"],
#         }

#     # ---- Constraints (PK, FK, UNIQUE, CHECK) ----
#     cur.execute(
#         """
#         SELECT
#             tc.constraint_name,
#             tc.constraint_type,
#             tc.table_name,
#             kcu.column_name,
#             ccu.table_name  AS foreign_table,
#             ccu.column_name AS foreign_column
#         FROM information_schema.table_constraints tc
#         JOIN information_schema.key_column_usage kcu
#             ON tc.constraint_name = kcu.constraint_name
#             AND tc.table_schema = kcu.table_schema
#         LEFT JOIN information_schema.constraint_column_usage ccu
#             ON tc.constraint_name = ccu.constraint_name
#             AND tc.constraint_type = 'FOREIGN KEY'
#             AND tc.table_schema = ccu.table_schema
#         WHERE tc.table_schema = %s
#         ORDER BY tc.table_name, tc.constraint_name
#         """,
#         (schema_name,),
#     )
#     for row in cur.fetchall():
#         table = schema.get(row["table_name"])
#         if table is None:
#             continue
#         entry = table["constraints"].setdefault(
#             row["constraint_name"],
#             {
#                 "type": row["constraint_type"],
#                 "columns": [],
#                 "foreign_table": row["foreign_table"],
#                 "foreign_columns": [],
#             },
#         )
#         if row["column_name"] and row["column_name"] not in entry["columns"]:
#             entry["columns"].append(row["column_name"])
#         if row["foreign_column"] and row["foreign_column"] not in entry["foreign_columns"]:
#             entry["foreign_columns"].append(row["foreign_column"])

#     # ---- Exact column types (e.g. numeric(10,2), integer[], custom types) ----
#     cur.execute(
#         """
#         SELECT cl.relname AS table_name, a.attname AS column_name,
#                format_type(a.atttypid, a.atttypmod) AS full_type
#         FROM pg_attribute a
#         JOIN pg_class cl ON cl.oid = a.attrelid
#         JOIN pg_namespace n ON n.oid = cl.relnamespace
#         WHERE n.nspname = %s AND a.attnum > 0 AND NOT a.attisdropped
#           AND cl.relkind IN ('r', 'p')
#         """,
#         (schema_name,),
#     )
#     for row in cur.fetchall():
#         table = schema.get(row["table_name"])
#         if table and row["column_name"] in table["columns"]:
#             table["columns"][row["column_name"]]["full_type"] = row["full_type"]

#     # ---- Full constraint definitions (also picks up CHECK constraints) ----
#     cur.execute(
#         """
#         SELECT cl.relname AS table_name, c.conname, c.contype,
#                pg_get_constraintdef(c.oid) AS definition
#         FROM pg_constraint c
#         JOIN pg_class cl ON cl.oid = c.conrelid
#         JOIN pg_namespace n ON n.oid = cl.relnamespace
#         WHERE n.nspname = %s AND c.contype IN ('p', 'f', 'u', 'c')
#         """,
#         (schema_name,),
#     )
#     for row in cur.fetchall():
#         table = schema.get(row["table_name"])
#         if table is None:
#             continue
#         entry = table["constraints"].setdefault(
#             row["conname"],
#             {
#                 "type": "CHECK",
#                 "columns": [],
#                 "foreign_table": None,
#                 "foreign_columns": [],
#             },
#         )
#         entry["definition"] = row["definition"]

#     # ---- Indexes ----
#     cur.execute(
#         """
#         SELECT indexname, tablename, indexdef
#         FROM pg_indexes
#         WHERE schemaname = %s
#         ORDER BY tablename, indexname
#         """,
#         (schema_name,),
#     )
#     for row in cur.fetchall():
#         table = schema.get(row["tablename"])
#         if table is None:
#             continue
#         table["indexes"][row["indexname"]] = row["indexdef"]

#     cur.close()
#     return schema


# # --------------------------------------------------------------------------
# # 3. Comparison
# # --------------------------------------------------------------------------

# def compare_schemas(old_schema: dict, new_schema: dict) -> dict:
#     changes = []

#     old_tables = set(old_schema.keys())
#     new_tables = set(new_schema.keys())

#     for table in sorted(new_tables - old_tables):
#         changes.append({"type": "TABLE_ADDED", "table": table})

#     for table in sorted(old_tables - new_tables):
#         changes.append({"type": "TABLE_REMOVED", "table": table})

#     for table in sorted(old_tables & new_tables):
#         old_t = old_schema[table]
#         new_t = new_schema[table]

#         # --- Columns ---
#         old_cols = set(old_t["columns"].keys())
#         new_cols = set(new_t["columns"].keys())

#         for col in sorted(new_cols - old_cols):
#             changes.append({"type": "COLUMN_ADDED", "table": table, "column": col})

#         for col in sorted(old_cols - new_cols):
#             changes.append({"type": "COLUMN_REMOVED", "table": table, "column": col})

#         for col in sorted(old_cols & new_cols):
#             old_def = old_t["columns"][col]
#             new_def = new_t["columns"][col]
#             if old_def != new_def:
#                 changes.append(
#                     {
#                         "type": "COLUMN_CHANGED",
#                         "table": table,
#                         "column": col,
#                         "old": old_def,
#                         "new": new_def,
#                     }
#                 )

#         # --- Constraints ---
#         old_cons = set(old_t["constraints"].keys())
#         new_cons = set(new_t["constraints"].keys())

#         for name in sorted(new_cons - old_cons):
#             changes.append(
#                 {
#                     "type": "CONSTRAINT_ADDED",
#                     "table": table,
#                     "name": name,
#                     "new": new_t["constraints"][name],
#                 }
#             )

#         for name in sorted(old_cons - new_cons):
#             changes.append(
#                 {
#                     "type": "CONSTRAINT_REMOVED",
#                     "table": table,
#                     "name": name,
#                     "old": old_t["constraints"][name],
#                 }
#             )

#         for name in sorted(old_cons & new_cons):
#             old_def = old_t["constraints"][name]
#             new_def = new_t["constraints"][name]
#             if old_def != new_def:
#                 changes.append(
#                     {
#                         "type": "CONSTRAINT_CHANGED",
#                         "table": table,
#                         "name": name,
#                         "old": old_def,
#                         "new": new_def,
#                     }
#                 )

#         # --- Indexes ---
#         old_idx = set(old_t["indexes"].keys())
#         new_idx = set(new_t["indexes"].keys())

#         for name in sorted(new_idx - old_idx):
#             changes.append(
#                 {
#                     "type": "INDEX_ADDED",
#                     "table": table,
#                     "name": name,
#                     "new": new_t["indexes"][name],
#                 }
#             )

#         for name in sorted(old_idx - new_idx):
#             changes.append(
#                 {
#                     "type": "INDEX_REMOVED",
#                     "table": table,
#                     "name": name,
#                     "old": old_t["indexes"][name],
#                 }
#             )

#         for name in sorted(old_idx & new_idx):
#             if old_t["indexes"][name] != new_t["indexes"][name]:
#                 changes.append(
#                     {
#                         "type": "INDEX_CHANGED",
#                         "table": table,
#                         "name": name,
#                         "old": old_t["indexes"][name],
#                         "new": new_t["indexes"][name],
#                     }
#                 )

#     summary: dict = {}
#     for change in changes:
#         summary[change["type"]] = summary.get(change["type"], 0) + 1

#     return {
#         "summary": summary,
#         "changes": changes,
#     }


# # --------------------------------------------------------------------------
# # 3b. Migration SQL generation (makes OLD match NEW)
# # --------------------------------------------------------------------------

# def _q(name: str) -> str:
#     return '"' + name.replace('"', '""') + '"'


# def _tbl(table: str) -> str:
#     return f"{_q(SCHEMA_NAME)}.{_q(table)}"


# def _col_type(col_def: dict) -> str:
#     if col_def.get("full_type"):
#         return col_def["full_type"]
#     if col_def.get("length"):
#         return f"{col_def['type']}({col_def['length']})"
#     return col_def["type"]


# def _column_sql(name: str, col_def: dict) -> str:
#     sql = f"{_q(name)} {_col_type(col_def)}"
#     if col_def.get("default") is not None:
#         sql += f" DEFAULT {col_def['default']}"
#     if col_def.get("nullable") == "NO":
#         sql += " NOT NULL"
#     return sql


# def _sequence_stmts(table: str, col: str, col_def: dict, own: bool = True):
#     """
#     If the column default uses nextval('some_seq'), return statements that
#     create the sequence (before the table) and attach it to the column
#     (after the table), like SERIAL does.
#     """
#     m = re.search(r"nextval\('([^']+)'::regclass\)", col_def.get("default") or "")
#     if not m:
#         return [], []
#     seq = m.group(1)
#     col_type = _col_type(col_def)
#     seq_type = col_type if col_type in ("smallint", "integer") else "bigint"
#     create = [f"CREATE SEQUENCE IF NOT EXISTS {seq} AS {seq_type};"]
#     owned = [f"ALTER SEQUENCE {seq} OWNED BY {_tbl(table)}.{_q(col)};"] if own else []
#     return create, owned


# def generate_migration(old_schema: dict, new_schema: dict, changes: list):
#     """
#     Returns (safe_statements, destructive_statements, warnings).
#     Statements are ordered so dependencies are respected.
#     """
#     create_seqs, own_seqs = [], []
#     create_tables, drop_cons, drop_idx = [], [], []
#     col_changes, add_cons, add_fks, add_idx = [], [], [], []
#     destructive, warnings = [], []

#     def add_sequences(table, col, col_def, own=True):
#         create, owned = _sequence_stmts(table, col, col_def, own)
#         for stmt in create:
#             if stmt not in create_seqs:
#                 create_seqs.append(stmt)
#         own_seqs.extend(owned)

#     def add_constraint(table, name, con):
#         definition = con.get("definition")
#         if not definition:
#             warnings.append(f"No definition for constraint {table}.{name}; skipped.")
#             return
#         stmt = f"ALTER TABLE {_tbl(table)} ADD CONSTRAINT {_q(name)} {definition};"
#         (add_fks if con["type"] == "FOREIGN KEY" else add_cons).append(stmt)

#     for ch in changes:
#         t, kind = ch["table"], ch["type"]

#         if kind == "TABLE_ADDED":
#             nt = new_schema[t]
#             for c, d in nt["columns"].items():
#                 add_sequences(t, c, d)
#             cols = ",\n    ".join(_column_sql(c, d) for c, d in nt["columns"].items())
#             create_tables.append(f"CREATE TABLE {_tbl(t)} (\n    {cols}\n);")
#             for cname, con in nt["constraints"].items():
#                 add_constraint(t, cname, con)
#             for iname, idef in nt["indexes"].items():
#                 if iname not in nt["constraints"]:  # skip PK/UNIQUE-backed indexes
#                     add_idx.append(idef + ";")

#         elif kind == "TABLE_REMOVED":
#             destructive.append(f"DROP TABLE {_tbl(t)};")

#         elif kind == "COLUMN_ADDED":
#             d = new_schema[t]["columns"][ch["column"]]
#             add_sequences(t, ch["column"], d, own=False)
#             col_changes.append(f"ALTER TABLE {_tbl(t)} ADD COLUMN {_column_sql(ch['column'], d)};")

#         elif kind == "COLUMN_REMOVED":
#             destructive.append(f"ALTER TABLE {_tbl(t)} DROP COLUMN {_q(ch['column'])};")

#         elif kind == "COLUMN_CHANGED":
#             c, o, n = _q(ch["column"]), ch["old"], ch["new"]
#             if _col_type(o) != _col_type(n):
#                 col_changes.append(
#                     f"ALTER TABLE {_tbl(t)} ALTER COLUMN {c} TYPE {_col_type(n)} "
#                     f"USING {c}::{_col_type(n)};"
#                 )
#             if o["nullable"] != n["nullable"]:
#                 action = "SET NOT NULL" if n["nullable"] == "NO" else "DROP NOT NULL"
#                 col_changes.append(f"ALTER TABLE {_tbl(t)} ALTER COLUMN {c} {action};")
#             if o["default"] != n["default"]:
#                 action = "DROP DEFAULT" if n["default"] is None else f"SET DEFAULT {n['default']}"
#                 if n["default"] is not None:
#                     add_sequences(t, ch["column"], n, own=False)
#                 col_changes.append(f"ALTER TABLE {_tbl(t)} ALTER COLUMN {c} {action};")

#         elif kind == "CONSTRAINT_ADDED":
#             add_constraint(t, ch["name"], ch["new"])

#         elif kind == "CONSTRAINT_REMOVED":
#             drop_cons.append(f"ALTER TABLE {_tbl(t)} DROP CONSTRAINT {_q(ch['name'])};")

#         elif kind == "CONSTRAINT_CHANGED":
#             drop_cons.append(f"ALTER TABLE {_tbl(t)} DROP CONSTRAINT {_q(ch['name'])};")
#             add_constraint(t, ch["name"], ch["new"])

#         elif kind == "INDEX_ADDED":
#             if ch["name"] not in new_schema[t]["constraints"]:
#                 add_idx.append(ch["new"] + ";")

#         elif kind == "INDEX_REMOVED":
#             if ch["name"] not in old_schema[t]["constraints"]:
#                 drop_idx.append(f"DROP INDEX {_q(SCHEMA_NAME)}.{_q(ch['name'])};")

#         elif kind == "INDEX_CHANGED":
#             if ch["name"] not in new_schema[t]["constraints"]:
#                 drop_idx.append(f"DROP INDEX {_q(SCHEMA_NAME)}.{_q(ch['name'])};")
#                 add_idx.append(ch["new"] + ";")

#     safe = (create_seqs + create_tables + own_seqs + drop_cons + drop_idx + col_changes
#             + add_cons + add_fks + add_idx)
#     return safe, destructive, warnings


# def write_sql_report(safe: list, destructive: list, path: Path) -> None:
#     path.parent.mkdir(parents=True, exist_ok=True)
#     parts = ["BEGIN;", "", "-- Safe changes"] + safe
#     if destructive:
#         parts += ["", "-- DESTRUCTIVE changes (data loss!) --"] + destructive
#     parts += ["", "COMMIT;", ""]
#     path.write_text("\n".join(parts), encoding="utf-8")


# def ask_yes_no(question: str) -> bool:
#     return input(f"{question} (yes/no): ").strip().lower() in ("yes", "y")


# def apply_to_old_db(statements: list) -> bool:
#     """Runs all statements in ONE transaction; rolls back on any error."""
#     conn = get_connection(OLD_DB)
#     try:
#         with conn.cursor() as cur:
#             for stmt in statements:
#                 cur.execute(stmt)
#         conn.commit()
#         return True
#     except Exception as exc:
#         conn.rollback()
#         print(f"\nERROR: {exc}")
#         print("Transaction rolled back - the old database was NOT changed.")
#         return False
#     finally:
#         conn.close()


# # --------------------------------------------------------------------------
# # 4. Report generation
# # --------------------------------------------------------------------------

# def write_json_report(report: dict, path: Path) -> None:
#     path.parent.mkdir(parents=True, exist_ok=True)
#     path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


# def generate_html_report(report: dict, path: Path, old_label: str, new_label: str) -> None:
#     rows = []

#     for change in report["changes"]:
#         change_type = change["type"]

#         if "ADDED" in change_type:
#             color = "#dcfce7"
#         elif "REMOVED" in change_type:
#             color = "#fee2e2"
#         else:
#             color = "#fef3c7"

#         rows.append(
#             f"""
#             <tr style="background:{color}">
#                 <td>{html.escape(change_type)}</td>
#                 <td>{html.escape(change.get("table", ""))}</td>
#                 <td>{html.escape(change.get("column", change.get("name", "")))}</td>
#                 <td><pre>{html.escape(str(change.get("old", "")))}</pre></td>
#                 <td><pre>{html.escape(str(change.get("new", "")))}</pre></td>
#             </tr>
#             """
#         )

#     summary = "".join(
#         f"<li>{html.escape(k)}: {v}</li>" for k, v in report["summary"].items()
#     )

#     page = f"""
# <!DOCTYPE html>
# <html>
# <head>
#     <meta charset="utf-8">
#     <title>PostgreSQL Schema Diff</title>
#     <style>
#         body {{
#             font-family: Arial, sans-serif;
#             margin: 30px;
#         }}
#         table {{
#             border-collapse: collapse;
#             width: 100%;
#         }}
#         th, td {{
#             border: 1px solid #ddd;
#             padding: 10px;
#             text-align: left;
#             vertical-align: top;
#         }}
#         th {{
#             background: #1f2937;
#             color: white;
#         }}
#         pre {{
#             white-space: pre-wrap;
#             max-width: 350px;
#         }}
#     </style>
# </head>
# <body>
#     <h1>PostgreSQL Schema Comparison</h1>
#     <p>Old: {html.escape(old_label)} | New: {html.escape(new_label)}</p>

#     <h2>Summary</h2>
#     <ul>{summary}</ul>

#     <h2>Detailed Changes</h2>
#     <table>
#         <tr>
#             <th>Change</th>
#             <th>Table</th>
#             <th>Column / Object</th>
#             <th>Old Definition</th>
#             <th>New Definition</th>
#         </tr>
#         {''.join(rows)}
#     </table>
# </body>
# </html>
# """
#     path.parent.mkdir(parents=True, exist_ok=True)
#     path.write_text(page, encoding="utf-8")


# # --------------------------------------------------------------------------
# # 5. Main
# # --------------------------------------------------------------------------

# def main() -> None:
#     print(f"Connecting to old database: {OLD_DB['dbname']}@{OLD_DB['host']}")
#     old_conn = get_connection(OLD_DB)

#     print(f"Connecting to new database: {NEW_DB['dbname']}@{NEW_DB['host']}")
#     new_conn = get_connection(NEW_DB)

#     try:
#         print(f"Reading schema '{SCHEMA_NAME}' from old database...")
#         old_schema = get_schema(old_conn, SCHEMA_NAME)

#         print(f"Reading schema '{SCHEMA_NAME}' from new database...")
#         new_schema = get_schema(new_conn, SCHEMA_NAME)
#     finally:
#         old_conn.close()
#         new_conn.close()

#     print("Comparing schemas...")
#     report = compare_schemas(old_schema, new_schema)

#     write_json_report(report, JSON_REPORT_PATH)
#     print(f"JSON report written to {JSON_REPORT_PATH}")

#     generate_html_report(
#         report,
#         HTML_REPORT_PATH,
#         old_label=OLD_DB["dbname"],
#         new_label=NEW_DB["dbname"],
#     )
#     print(f"HTML report written to {HTML_REPORT_PATH}")

#     print("\nSummary:")
#     for change_type, count in report["summary"].items():
#         print(f"  {change_type}: {count}")

#     if not report["changes"]:
#         print("No schema differences found.")
#         return

#     # ---- Optional: apply changes to the OLD database ----
#     safe, destructive, warnings = generate_migration(
#         old_schema, new_schema, report["changes"]
#     )
#     write_sql_report(safe, destructive, SQL_REPORT_PATH)
#     print(f"\nMigration SQL written to {SQL_REPORT_PATH}")

#     for w in warnings:
#         print(f"  WARNING: {w}")

#     print("\n--- Statements that would run on the OLD database ---")
#     for stmt in safe:
#         print(stmt)
#     if destructive:
#         print("\n--- DESTRUCTIVE statements (separate confirmation) ---")
#         for stmt in destructive:
#             print(stmt)

#     if not ask_yes_no(
#         f"\nApply {len(safe)} change(s) to OLD database "
#         f"'{OLD_DB['dbname']}'@{OLD_DB['host']}?"
#     ):
#         print("No changes applied.")
#         return

#     to_run = list(safe)
#     if destructive and ask_yes_no(
#         f"Also run {len(destructive)} DESTRUCTIVE statement(s) "
#         f"(drops tables/columns, data will be lost)?"
#     ):
#         to_run += destructive

#     if apply_to_old_db(to_run):
#         print(f"Applied {len(to_run)} statement(s) successfully.")
#         verify = get_connection(OLD_DB)
#         try:
#             remaining = compare_schemas(get_schema(verify, SCHEMA_NAME), new_schema)
#         finally:
#             verify.close()
#         print(f"Remaining differences after apply: {len(remaining['changes'])}")


# if __name__ == "__main__":
#     main()

















"""
schema_diff.py

Compares the schema (tables, columns, constraints, indexes) of two
PostgreSQL databases ("old" and "new") and produces:

  - reports/schema_diff.json  -> machine-readable diff
  - reports/schema_diff.html  -> human-readable diff report
  - reports/migration.sql     -> SQL that would make "old" match "new"

After the report, you are asked whether to APPLY the changes to the old
database. Answer "yes" to proceed; anything else exits without changes.
Destructive changes (dropping tables/columns) need a separate confirmation.

All connection details and settings are read from a `.env` file
(see `.env.example`). Nothing is hard-coded in this file.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # then edit .env with your real values
    python schema_diff.py
"""

import html
import json
import os
import re
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# --------------------------------------------------------------------------
# 0. Configuration (all values come from environment / .env, nothing hard-coded)
# --------------------------------------------------------------------------

load_dotenv()


def _require_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Check your .env file (see .env.example)."
        )
    return value


OLD_DB = {
    "host": _require_env("OLD_DB_HOST"),
    "port": _require_env("OLD_DB_PORT", "5432"),
    "dbname": _require_env("OLD_DB_NAME"),
    "user": _require_env("OLD_DB_USER"),
    "password": _require_env("OLD_DB_PASSWORD"),
}

NEW_DB = {
    "host": _require_env("NEW_DB_HOST"),
    "port": _require_env("NEW_DB_PORT", "5432"),
    "dbname": _require_env("NEW_DB_NAME"),
    "user": _require_env("NEW_DB_USER"),
    "password": _require_env("NEW_DB_PASSWORD"),
}

SCHEMA_NAME = os.getenv("PG_SCHEMA", "public")
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
JSON_REPORT_PATH = REPORTS_DIR / os.getenv("JSON_REPORT_NAME", "schema_diff.json")
HTML_REPORT_PATH = REPORTS_DIR / os.getenv("HTML_REPORT_NAME", "schema_diff.html")
SQL_REPORT_PATH = REPORTS_DIR / os.getenv("SQL_REPORT_NAME", "migration.sql")
ARCHIVE_SCHEMA = os.getenv("ARCHIVE_SCHEMA", "schema_diff_archive")


# --------------------------------------------------------------------------
# 1. Connection helper
# --------------------------------------------------------------------------

def get_connection(config: dict):
    return psycopg2.connect(
        host=config["host"],
        port=config["port"],
        dbname=config["dbname"],
        user=config["user"],
        password=config["password"],
    )


# --------------------------------------------------------------------------
# 2. Schema extraction
# --------------------------------------------------------------------------

def get_schema(conn, schema_name: str) -> dict:
    """
    Returns a dict describing every table in `schema_name`:

    {
        "table_name": {
            "columns": {
                "col_name": {
                    "type": "character varying",
                    "length": 50,
                    "nullable": "YES"/"NO",
                    "default": "..." or None,
                }
            },
            "constraints": {
                "constraint_name": {
                    "type": "PRIMARY KEY" / "FOREIGN KEY" / "UNIQUE" / "CHECK",
                    "columns": ["col1", "col2"],
                    "foreign_table": "other_table" or None,
                    "foreign_columns": ["col"] or [],
                }
            },
            "indexes": {
                "index_name": "CREATE INDEX ... definition"
            },
        }
    }
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    schema: dict = {}

    # ---- Tables ----
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        (schema_name,),
    )
    for row in cur.fetchall():
        schema[row["table_name"]] = {
            "columns": {},
            "constraints": {},
            "indexes": {},
        }

    # ---- Columns ----
    cur.execute(
        """
        SELECT table_name, column_name, data_type,
               character_maximum_length, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = %s
        ORDER BY table_name, ordinal_position
        """,
        (schema_name,),
    )
    for row in cur.fetchall():
        table = schema.get(row["table_name"])
        if table is None:
            continue
        table["columns"][row["column_name"]] = {
            "type": row["data_type"],
            "length": row["character_maximum_length"],
            "nullable": row["is_nullable"],
            "default": row["column_default"],
        }

    # ---- Constraints (PK, FK, UNIQUE, CHECK) ----
    cur.execute(
        """
        SELECT
            tc.constraint_name,
            tc.constraint_type,
            tc.table_name,
            kcu.column_name,
            ccu.table_name  AS foreign_table,
            ccu.column_name AS foreign_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        LEFT JOIN information_schema.constraint_column_usage ccu
            ON tc.constraint_name = ccu.constraint_name
            AND tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = ccu.table_schema
        WHERE tc.table_schema = %s
        ORDER BY tc.table_name, tc.constraint_name
        """,
        (schema_name,),
    )
    for row in cur.fetchall():
        table = schema.get(row["table_name"])
        if table is None:
            continue
        entry = table["constraints"].setdefault(
            row["constraint_name"],
            {
                "type": row["constraint_type"],
                "columns": [],
                "foreign_table": row["foreign_table"],
                "foreign_columns": [],
            },
        )
        if row["column_name"] and row["column_name"] not in entry["columns"]:
            entry["columns"].append(row["column_name"])
        if row["foreign_column"] and row["foreign_column"] not in entry["foreign_columns"]:
            entry["foreign_columns"].append(row["foreign_column"])

    # ---- Exact column types (e.g. numeric(10,2), integer[], custom types) ----
    cur.execute(
        """
        SELECT cl.relname AS table_name, a.attname AS column_name,
               format_type(a.atttypid, a.atttypmod) AS full_type
        FROM pg_attribute a
        JOIN pg_class cl ON cl.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = %s AND a.attnum > 0 AND NOT a.attisdropped
          AND cl.relkind IN ('r', 'p')
        """,
        (schema_name,),
    )
    for row in cur.fetchall():
        table = schema.get(row["table_name"])
        if table and row["column_name"] in table["columns"]:
            table["columns"][row["column_name"]]["full_type"] = row["full_type"]

    # ---- Full constraint definitions (also picks up CHECK constraints) ----
    cur.execute(
        """
        SELECT cl.relname AS table_name, c.conname, c.contype,
               pg_get_constraintdef(c.oid) AS definition
        FROM pg_constraint c
        JOIN pg_class cl ON cl.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = %s AND c.contype IN ('p', 'f', 'u', 'c')
        """,
        (schema_name,),
    )
    for row in cur.fetchall():
        table = schema.get(row["table_name"])
        if table is None:
            continue
        entry = table["constraints"].setdefault(
            row["conname"],
            {
                "type": "CHECK",
                "columns": [],
                "foreign_table": None,
                "foreign_columns": [],
            },
        )
        entry["definition"] = row["definition"]

    # ---- Indexes ----
    cur.execute(
        """
        SELECT indexname, tablename, indexdef
        FROM pg_indexes
        WHERE schemaname = %s
        ORDER BY tablename, indexname
        """,
        (schema_name,),
    )
    for row in cur.fetchall():
        table = schema.get(row["tablename"])
        if table is None:
            continue
        table["indexes"][row["indexname"]] = row["indexdef"]

    cur.close()
    return schema


# --------------------------------------------------------------------------
# 3. Comparison
# --------------------------------------------------------------------------

def compare_schemas(old_schema: dict, new_schema: dict) -> dict:
    changes = []

    old_tables = set(old_schema.keys())
    new_tables = set(new_schema.keys())

    for table in sorted(new_tables - old_tables):
        changes.append({"type": "TABLE_ADDED", "table": table})

    for table in sorted(old_tables - new_tables):
        changes.append({"type": "TABLE_REMOVED", "table": table})

    for table in sorted(old_tables & new_tables):
        old_t = old_schema[table]
        new_t = new_schema[table]

        # --- Columns ---
        old_cols = set(old_t["columns"].keys())
        new_cols = set(new_t["columns"].keys())

        for col in sorted(new_cols - old_cols):
            changes.append({"type": "COLUMN_ADDED", "table": table, "column": col})

        for col in sorted(old_cols - new_cols):
            changes.append({"type": "COLUMN_REMOVED", "table": table, "column": col})

        for col in sorted(old_cols & new_cols):
            old_def = old_t["columns"][col]
            new_def = new_t["columns"][col]
            if old_def != new_def:
                changes.append(
                    {
                        "type": "COLUMN_CHANGED",
                        "table": table,
                        "column": col,
                        "old": old_def,
                        "new": new_def,
                    }
                )

        # --- Constraints ---
        old_cons = set(old_t["constraints"].keys())
        new_cons = set(new_t["constraints"].keys())

        for name in sorted(new_cons - old_cons):
            changes.append(
                {
                    "type": "CONSTRAINT_ADDED",
                    "table": table,
                    "name": name,
                    "new": new_t["constraints"][name],
                }
            )

        for name in sorted(old_cons - new_cons):
            changes.append(
                {
                    "type": "CONSTRAINT_REMOVED",
                    "table": table,
                    "name": name,
                    "old": old_t["constraints"][name],
                }
            )

        for name in sorted(old_cons & new_cons):
            old_def = old_t["constraints"][name]
            new_def = new_t["constraints"][name]
            if old_def != new_def:
                changes.append(
                    {
                        "type": "CONSTRAINT_CHANGED",
                        "table": table,
                        "name": name,
                        "old": old_def,
                        "new": new_def,
                    }
                )

        # --- Indexes ---
        old_idx = set(old_t["indexes"].keys())
        new_idx = set(new_t["indexes"].keys())

        for name in sorted(new_idx - old_idx):
            changes.append(
                {
                    "type": "INDEX_ADDED",
                    "table": table,
                    "name": name,
                    "new": new_t["indexes"][name],
                }
            )

        for name in sorted(old_idx - new_idx):
            changes.append(
                {
                    "type": "INDEX_REMOVED",
                    "table": table,
                    "name": name,
                    "old": old_t["indexes"][name],
                }
            )

        for name in sorted(old_idx & new_idx):
            if old_t["indexes"][name] != new_t["indexes"][name]:
                changes.append(
                    {
                        "type": "INDEX_CHANGED",
                        "table": table,
                        "name": name,
                        "old": old_t["indexes"][name],
                        "new": new_t["indexes"][name],
                    }
                )

    summary: dict = {}
    for change in changes:
        summary[change["type"]] = summary.get(change["type"], 0) + 1

    return {
        "summary": summary,
        "changes": changes,
    }


# --------------------------------------------------------------------------
# 3b. Migration SQL generation (makes OLD match NEW)
# --------------------------------------------------------------------------

def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _tbl(table: str) -> str:
    return f"{_q(SCHEMA_NAME)}.{_q(table)}"


def _col_type(col_def: dict) -> str:
    if col_def.get("full_type"):
        return col_def["full_type"]
    if col_def.get("length"):
        return f"{col_def['type']}({col_def['length']})"
    return col_def["type"]


def _column_sql(name: str, col_def: dict) -> str:
    sql = f"{_q(name)} {_col_type(col_def)}"
    if col_def.get("default") is not None:
        sql += f" DEFAULT {col_def['default']}"
    if col_def.get("nullable") == "NO":
        sql += " NOT NULL"
    return sql


def _sequence_stmts(table: str, col: str, col_def: dict, own: bool = True):
    """
    If the column default uses nextval('some_seq'), return statements that
    create the sequence (before the table) and attach it to the column
    (after the table), like SERIAL does.
    """
    m = re.search(r"nextval\('([^']+)'::regclass\)", col_def.get("default") or "")
    if not m:
        return [], []
    seq = m.group(1)
    col_type = _col_type(col_def)
    seq_type = col_type if col_type in ("smallint", "integer") else "bigint"
    create = [f"CREATE SEQUENCE IF NOT EXISTS {seq} AS {seq_type};"]
    owned = [f"ALTER SEQUENCE {seq} OWNED BY {_tbl(table)}.{_q(col)};"] if own else []
    return create, owned


def generate_migration(old_schema: dict, new_schema: dict, changes: list):
    """
    Returns (safe_statements, destructive_statements, warnings).
    Statements are ordered so dependencies are respected.
    """
    create_seqs, own_seqs = [], []
    create_tables, drop_cons, drop_idx = [], [], []
    col_changes, add_cons, add_fks, add_idx = [], [], [], []
    destructive, warnings = [], []

    def add_sequences(table, col, col_def, own=True):
        create, owned = _sequence_stmts(table, col, col_def, own)
        for stmt in create:
            if stmt not in create_seqs:
                create_seqs.append(stmt)
        own_seqs.extend(owned)

    def add_constraint(table, name, con):
        definition = con.get("definition")
        if not definition:
            warnings.append(f"No definition for constraint {table}.{name}; skipped.")
            return
        stmt = f"ALTER TABLE {_tbl(table)} ADD CONSTRAINT {_q(name)} {definition};"
        (add_fks if con["type"] == "FOREIGN KEY" else add_cons).append(stmt)

    for ch in changes:
        t, kind = ch["table"], ch["type"]

        if kind == "TABLE_ADDED":
            nt = new_schema[t]
            for c, d in nt["columns"].items():
                add_sequences(t, c, d)
            cols = ",\n    ".join(_column_sql(c, d) for c, d in nt["columns"].items())
            create_tables.append(f"CREATE TABLE {_tbl(t)} (\n    {cols}\n);")
            for cname, con in nt["constraints"].items():
                add_constraint(t, cname, con)
            for iname, idef in nt["indexes"].items():
                if iname not in nt["constraints"]:  # skip PK/UNIQUE-backed indexes
                    add_idx.append(idef + ";")

        elif kind == "TABLE_REMOVED":
            destructive.append(f"DROP TABLE {_tbl(t)};")

        elif kind == "COLUMN_ADDED":
            d = new_schema[t]["columns"][ch["column"]]
            add_sequences(t, ch["column"], d, own=False)
            col_changes.append(f"ALTER TABLE {_tbl(t)} ADD COLUMN {_column_sql(ch['column'], d)};")

        elif kind == "COLUMN_REMOVED":
            destructive.append(f"ALTER TABLE {_tbl(t)} DROP COLUMN {_q(ch['column'])};")

        elif kind == "COLUMN_CHANGED":
            c, o, n = _q(ch["column"]), ch["old"], ch["new"]
            if _col_type(o) != _col_type(n):
                col_changes.append(
                    f"ALTER TABLE {_tbl(t)} ALTER COLUMN {c} TYPE {_col_type(n)} "
                    f"USING {c}::{_col_type(n)};"
                )
            if o["nullable"] != n["nullable"]:
                action = "SET NOT NULL" if n["nullable"] == "NO" else "DROP NOT NULL"
                col_changes.append(f"ALTER TABLE {_tbl(t)} ALTER COLUMN {c} {action};")
            if o["default"] != n["default"]:
                action = "DROP DEFAULT" if n["default"] is None else f"SET DEFAULT {n['default']}"
                if n["default"] is not None:
                    add_sequences(t, ch["column"], n, own=False)
                col_changes.append(f"ALTER TABLE {_tbl(t)} ALTER COLUMN {c} {action};")

        elif kind == "CONSTRAINT_ADDED":
            add_constraint(t, ch["name"], ch["new"])

        elif kind == "CONSTRAINT_REMOVED":
            drop_cons.append(f"ALTER TABLE {_tbl(t)} DROP CONSTRAINT {_q(ch['name'])};")

        elif kind == "CONSTRAINT_CHANGED":
            drop_cons.append(f"ALTER TABLE {_tbl(t)} DROP CONSTRAINT {_q(ch['name'])};")
            add_constraint(t, ch["name"], ch["new"])

        elif kind == "INDEX_ADDED":
            if ch["name"] not in new_schema[t]["constraints"]:
                add_idx.append(ch["new"] + ";")

        elif kind == "INDEX_REMOVED":
            if ch["name"] not in old_schema[t]["constraints"]:
                drop_idx.append(f"DROP INDEX {_q(SCHEMA_NAME)}.{_q(ch['name'])};")

        elif kind == "INDEX_CHANGED":
            if ch["name"] not in new_schema[t]["constraints"]:
                drop_idx.append(f"DROP INDEX {_q(SCHEMA_NAME)}.{_q(ch['name'])};")
                add_idx.append(ch["new"] + ";")

    safe = (create_seqs + create_tables + own_seqs + drop_cons + drop_idx + col_changes
            + add_cons + add_fks + add_idx)
    return safe, destructive, warnings


def write_sql_report(safe: list, destructive: list, path: Path, archive: list | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = ["BEGIN;", ""]
    if archive:
        parts += ["-- Data backup (runs first, so nothing dropped is lost)"] + archive + [""]
    parts += ["-- Safe changes"] + safe
    if destructive:
        parts += ["", "-- DESTRUCTIVE changes (data is archived above) --"] + destructive
    parts += ["", "COMMIT;", ""]
    path.write_text("\n".join(parts), encoding="utf-8")


def ask_yes_no(question: str) -> bool:
    return input(f"{question} (yes/no): ").strip().lower() in ("yes", "y")


# --------------------------------------------------------------------------
# 3c. Data-protection helpers
# --------------------------------------------------------------------------

def build_archive_statements(changes: list, ts: str):
    """
    Every table that loses a column (or is dropped entirely) is first copied
    into a separate archive schema, so the data can always be recovered.
    The archive schema is outside SCHEMA_NAME, so it never shows up as a diff.
    """
    tables = sorted(
        {c["table"] for c in changes if c["type"] in ("COLUMN_REMOVED", "TABLE_REMOVED")}
    )
    stmts, archives = [], []
    if tables:
        stmts.append(f"CREATE SCHEMA IF NOT EXISTS {_q(ARCHIVE_SCHEMA)};")
    for t in tables:
        name = f"{t}__{ts}"[:63]
        stmts.append(
            f"CREATE TABLE {_q(ARCHIVE_SCHEMA)}.{_q(name)} AS SELECT * FROM {_tbl(t)};"
        )
        archives.append({"source_table": t, "archive": f"{ARCHIVE_SCHEMA}.{name}"})
    return stmts, archives


def preflight_checks(old_schema: dict, changes: list, safe: list) -> list:
    """
    Read-only checks against the OLD db. Any statement that would fail or
    reject existing data (NOT NULL on NULLs, PK/UNIQUE on duplicates) is
    removed from `safe` and reported as skipped instead.
    """
    skipped = []
    conn = get_connection(OLD_DB)
    try:
        cur = conn.cursor()
        for ch in changes:
            t = ch["table"]
            if t not in old_schema:
                continue
            try:
                if (
                    ch["type"] == "COLUMN_CHANGED"
                    and ch["new"]["nullable"] == "NO"
                    and ch["old"]["nullable"] != "NO"
                ):
                    col = ch["column"]
                    cur.execute(f"SELECT count(*) FROM {_tbl(t)} WHERE {_q(col)} IS NULL")
                    n = cur.fetchone()[0]
                    if n:
                        stmt = f"ALTER TABLE {_tbl(t)} ALTER COLUMN {_q(col)} SET NOT NULL;"
                        if stmt in safe:
                            safe.remove(stmt)
                        skipped.append({
                            "statement": stmt,
                            "reason": f"{n} existing row(s) have NULL in {t}.{col}. "
                                      f"Fill or clean them, then re-run.",
                        })

                elif (
                    ch["type"] in ("CONSTRAINT_ADDED", "CONSTRAINT_CHANGED")
                    and ch["new"]["type"] in ("PRIMARY KEY", "UNIQUE")
                    and ch["new"]["columns"]
                    and all(c in old_schema[t]["columns"] for c in ch["new"]["columns"])
                ):
                    cols = ch["new"]["columns"]
                    collist = ", ".join(_q(c) for c in cols)
                    cur.execute(
                        f"SELECT count(*) FROM (SELECT 1 FROM {_tbl(t)} "
                        f"GROUP BY {collist} HAVING count(*) > 1) d"
                    )
                    dups = cur.fetchone()[0]
                    nulls = 0
                    if ch["new"]["type"] == "PRIMARY KEY":
                        cond = " OR ".join(f"{_q(c)} IS NULL" for c in cols)
                        cur.execute(f"SELECT count(*) FROM {_tbl(t)} WHERE {cond}")
                        nulls = cur.fetchone()[0]
                    if dups or nulls:
                        definition = ch["new"].get("definition", "")
                        add_stmt = f"ALTER TABLE {_tbl(t)} ADD CONSTRAINT {_q(ch['name'])} {definition};"
                        drop_stmt = f"ALTER TABLE {_tbl(t)} DROP CONSTRAINT {_q(ch['name'])};"
                        for st in (add_stmt, drop_stmt):
                            if st in safe:
                                safe.remove(st)
                        skipped.append({
                            "statement": add_stmt,
                            "reason": f"Existing data violates it ({dups} duplicate group(s), "
                                      f"{nulls} NULL row(s)) on {t}({', '.join(cols)}). "
                                      f"Constraint left unchanged.",
                        })
            except Exception as exc:  # a failed check must never block the run
                conn.rollback()
                skipped.append({"statement": f"(check for {ch['type']} on {t})",
                                "reason": f"Pre-flight check failed: {exc}"})
    finally:
        conn.close()
    return skipped


def table_row_counts(cur, tables: list) -> dict:
    counts = {}
    for t in tables:
        cur.execute(f"SELECT count(*) FROM {_tbl(t)}")
        counts[t] = cur.fetchone()[0]
    return counts


def apply_to_old_db(statements: list, tables: list, dropped_tables: list) -> dict:
    """
    Runs all statements in ONE transaction. Before committing, row counts of
    every surviving table are compared with the counts taken before; if any
    table lost rows, everything is rolled back.
    """
    result = {"ok": False, "error": None, "before": {}, "after": {}}
    guard = [t for t in tables if t not in dropped_tables]
    conn = get_connection(OLD_DB)
    try:
        with conn.cursor() as cur:
            result["before"] = table_row_counts(cur, tables)
            for stmt in statements:
                cur.execute(stmt)
            result["after"] = table_row_counts(cur, guard)
            lost = {
                t: (result["before"][t], result["after"][t])
                for t in guard
                if result["after"][t] < result["before"][t]
            }
            if lost:
                raise RuntimeError(f"Row counts decreased, aborting: {lost}")
        conn.commit()
        result["ok"] = True
    except Exception as exc:
        conn.rollback()
        result["error"] = str(exc)
        result["after"] = {}
        print(f"\nERROR: {exc}")
        print("Transaction rolled back - the old database was NOT changed.")
    finally:
        conn.close()
    return result


# --------------------------------------------------------------------------
# 4. Report generation
# --------------------------------------------------------------------------

def write_json_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def generate_html_report(report: dict, path: Path, old_label: str, new_label: str) -> None:
    rows = []

    for change in report["changes"]:
        change_type = change["type"]

        if "ADDED" in change_type:
            color = "#dcfce7"
        elif "REMOVED" in change_type:
            color = "#fee2e2"
        else:
            color = "#fef3c7"

        rows.append(
            f"""
            <tr style="background:{color}">
                <td>{html.escape(change_type)}</td>
                <td>{html.escape(change.get("table", ""))}</td>
                <td>{html.escape(change.get("column", change.get("name", "")))}</td>
                <td><pre>{html.escape(str(change.get("old", "")))}</pre></td>
                <td><pre>{html.escape(str(change.get("new", "")))}</pre></td>
            </tr>
            """
        )

    summary = "".join(
        f"<li>{html.escape(k)}: {v}</li>" for k, v in report["summary"].items()
    )

    page = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>PostgreSQL Schema Diff</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 30px;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 10px;
            text-align: left;
            vertical-align: top;
        }}
        th {{
            background: #1f2937;
            color: white;
        }}
        pre {{
            white-space: pre-wrap;
            max-width: 350px;
        }}
    </style>
</head>
<body>
    <h1>PostgreSQL Schema Comparison</h1>
    <p>Old: {html.escape(old_label)} | New: {html.escape(new_label)}</p>

    <h2>Summary</h2>
    <ul>{summary}</ul>

    <h2>Detailed Changes</h2>
    <table>
        <tr>
            <th>Change</th>
            <th>Table</th>
            <th>Column / Object</th>
            <th>Old Definition</th>
            <th>New Definition</th>
        </tr>
        {''.join(rows)}
    </table>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")


# --------------------------------------------------------------------------
# 4b. Final report (what was done / what was not done)
# --------------------------------------------------------------------------

def write_final_report(ctx: dict, html_path: Path, json_path: Path) -> None:
    e = html.escape
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(ctx, indent=2, default=str), encoding="utf-8")

    def table(headers, rows):
        if not rows:
            return "<p><em>None</em></p>"
        head = "".join(f"<th>{e(h)}</th>" for h in headers)
        body = "".join(
            "<tr>" + "".join(f"<td><pre>{e(str(c))}</pre></td>" for c in r) + "</tr>"
            for r in rows
        )
        return f"<table><tr>{head}</tr>{body}</table>"

    status_color = {
        "APPLIED": "#16a34a", "APPLIED WITH SKIPPED ITEMS": "#d97706",
        "NOT APPLIED": "#6b7280", "FAILED - ROLLED BACK": "#dc2626", "IN SYNC": "#16a34a",
    }.get(ctx["status"], "#6b7280")

    counts_rows = []
    for t, before in sorted(ctx.get("row_counts_before", {}).items()):
        after = ctx.get("row_counts_after", {}).get(t)
        counts_rows.append([
            t, before, "(table dropped / not applied)" if after is None else after,
            "" if after is None else ("OK" if after >= before else "ROWS LOST"),
        ])

    remaining = [
        [c["type"], c["table"], c.get("column", c.get("name", "")),
         c.get("old", ""), c.get("new", "")]
        for c in ctx["remaining_differences"]
    ]

    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Schema Sync - Final Report</title>
<style>
body{{font-family:Arial,sans-serif;margin:30px;color:#111}}
table{{border-collapse:collapse;width:100%;margin-bottom:20px}}
th,td{{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}}
th{{background:#1f2937;color:#fff}}
pre{{white-space:pre-wrap;margin:0;font-size:12px}}
.badge{{display:inline-block;padding:6px 14px;border-radius:6px;color:#fff;font-weight:bold;background:{status_color}}}
.box{{background:#f3f4f6;padding:12px;border-radius:6px;margin-bottom:20px}}
</style></head><body>
<h1>Schema Sync - Final Report</h1>
<p><span class="badge">{e(ctx['status'])}</span></p>
<div class="box">
<b>Run time:</b> {e(ctx['run_time'])}<br>
<b>Old database (modified):</b> {e(ctx['old_db'])}<br>
<b>New database (reference):</b> {e(ctx['new_db'])}<br>
<b>Differences found:</b> {ctx['differences_found']} &nbsp;|&nbsp;
<b>Statements applied:</b> {len(ctx['applied'])} &nbsp;|&nbsp;
<b>Skipped:</b> {len(ctx['skipped'])} &nbsp;|&nbsp;
<b>Not applied:</b> {len(ctx['not_applied'])} &nbsp;|&nbsp;
<b>Remaining differences:</b> {len(ctx['remaining_differences'])}
{('<br><b>Error:</b> ' + e(ctx['error'])) if ctx.get('error') else ''}
</div>

<h2>1. Done - applied to the old database</h2>
{table(['#', 'SQL'], [[i + 1, st] for i, st in enumerate(ctx['applied'])])}

<h2>2. Not done - skipped for data safety</h2>
{table(['SQL', 'Reason'], [[x['statement'], x['reason']] for x in ctx['skipped']])}

<h2>3. Not done - not applied</h2>
{table(['SQL', 'Reason'], [[x['statement'], x['reason']] for x in ctx['not_applied']])}

<h2>4. Differences still remaining after this run</h2>
{table(['Change', 'Table', 'Column / Object', 'Old', 'New'], remaining)}

<h2>5. Data protection</h2>
<p>Backups of every table that lost columns or was dropped
(schema <b>{e(ARCHIVE_SCHEMA)}</b>):</p>
{table(['Source table', 'Archive table'], [[a['source_table'], a['archive']] for a in ctx['archives']])}
<p>Row counts per table (before vs after):</p>
{table(['Table', 'Before', 'After', 'Check'], counts_rows)}
</body></html>"""
    html_path.write_text(page, encoding="utf-8")


# --------------------------------------------------------------------------
# 5. Main
# --------------------------------------------------------------------------

def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sql_path = SQL_REPORT_PATH.with_name(f"{SQL_REPORT_PATH.stem}_{ts}{SQL_REPORT_PATH.suffix}")
    final_html = REPORTS_DIR / f"final_report_{ts}.html"
    final_json = REPORTS_DIR / f"final_report_{ts}.json"

    print(f"Connecting to old database: {OLD_DB['dbname']}@{OLD_DB['host']}")
    old_conn = get_connection(OLD_DB)

    print(f"Connecting to new database: {NEW_DB['dbname']}@{NEW_DB['host']}")
    new_conn = get_connection(NEW_DB)

    try:
        print(f"Reading schema '{SCHEMA_NAME}' from old database...")
        old_schema = get_schema(old_conn, SCHEMA_NAME)

        print(f"Reading schema '{SCHEMA_NAME}' from new database...")
        new_schema = get_schema(new_conn, SCHEMA_NAME)
    finally:
        old_conn.close()
        new_conn.close()

    print("Comparing schemas...")
    report = compare_schemas(old_schema, new_schema)

    write_json_report(report, JSON_REPORT_PATH)
    print(f"JSON report written to {JSON_REPORT_PATH}")

    generate_html_report(
        report,
        HTML_REPORT_PATH,
        old_label=OLD_DB["dbname"],
        new_label=NEW_DB["dbname"],
    )
    print(f"HTML report written to {HTML_REPORT_PATH}")

    print("\nSummary:")
    for change_type, count in report["summary"].items():
        print(f"  {change_type}: {count}")

    ctx = {
        "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "old_db": f"{OLD_DB['dbname']}@{OLD_DB['host']}",
        "new_db": f"{NEW_DB['dbname']}@{NEW_DB['host']}",
        "status": "NOT APPLIED",
        "differences_found": len(report["changes"]),
        "applied": [], "skipped": [], "not_applied": [],
        "remaining_differences": report["changes"],
        "archives": [], "row_counts_before": {}, "row_counts_after": {},
        "error": None,
    }

    if not report["changes"]:
        print("No schema differences found.")
        ctx["status"] = "IN SYNC"
        write_final_report(ctx, final_html, final_json)
        print(f"Final report: {final_html}")
        return

    # ---- Build migration + data-safety plan ----
    safe, destructive, warnings = generate_migration(
        old_schema, new_schema, report["changes"]
    )
    skipped = preflight_checks(old_schema, report["changes"], safe)
    archive_stmts, archives = (
        build_archive_statements(report["changes"], ts) if destructive else ([], [])
    )
    write_sql_report(safe, destructive, sql_path, archive_stmts)
    print(f"\nMigration SQL written to {sql_path}")

    for w in warnings:
        print(f"  WARNING: {w}")
    for sk in skipped:
        print(f"  SKIPPED (data safety): {sk['statement']}\n      -> {sk['reason']}")

    print("\n--- Statements that would run on the OLD database ---")
    for stmt in safe:
        print(stmt)
    if destructive:
        print("\n--- DESTRUCTIVE statements (separate confirmation) ---")
        print("  (affected tables are copied to schema "
              f"'{ARCHIVE_SCHEMA}' first, so the data stays recoverable)")
        for stmt in destructive:
            print(stmt)

    ctx["skipped"] = skipped
    all_planned = safe + destructive

    if not ask_yes_no(
        f"\nApply {len(safe)} change(s) to OLD database "
        f"'{OLD_DB['dbname']}'@{OLD_DB['host']}?"
    ):
        print("No changes applied.")
        ctx["not_applied"] = [{"statement": st, "reason": "You answered 'no'."} for st in all_planned]
        write_final_report(ctx, final_html, final_json)
        print(f"Final report: {final_html}")
        return

    to_run = list(safe)
    run_destructive = bool(destructive) and ask_yes_no(
        f"Also run {len(destructive)} DESTRUCTIVE statement(s) "
        f"(columns/tables are archived first, then dropped)?"
    )
    if run_destructive:
        to_run = archive_stmts + to_run + destructive
    else:
        archives = []
        ctx["not_applied"] = [
            {"statement": st, "reason": "Destructive change - you answered 'no'."}
            for st in destructive
        ]

    dropped_tables = [c["table"] for c in report["changes"] if c["type"] == "TABLE_REMOVED"] \
        if run_destructive else []
    result = apply_to_old_db(to_run, list(old_schema.keys()), dropped_tables)
    ctx["row_counts_before"] = result["before"]
    ctx["row_counts_after"] = result["after"]

    if not result["ok"]:
        ctx["status"] = "FAILED - ROLLED BACK"
        ctx["error"] = result["error"]
        ctx["not_applied"] += [
            {"statement": st, "reason": "Transaction rolled back (see error)."} for st in to_run
        ]
        ctx["row_counts_after"] = {}
    else:
        ctx["applied"] = to_run
        ctx["archives"] = archives
        ctx["status"] = "APPLIED WITH SKIPPED ITEMS" if (skipped or ctx["not_applied"]) else "APPLIED"
        print(f"Applied {len(to_run)} statement(s) successfully.")
        verify = get_connection(OLD_DB)
        try:
            remaining = compare_schemas(get_schema(verify, SCHEMA_NAME), new_schema)
        finally:
            verify.close()
        ctx["remaining_differences"] = remaining["changes"]
        print(f"Remaining differences after apply: {len(remaining['changes'])}")
        for c in remaining["changes"]:
            print(f"  - {c['type']} on {c['table']} {c.get('column', c.get('name', ''))}")

    write_final_report(ctx, final_html, final_json)
    print(f"\nFinal report: {final_html}")


if __name__ == "__main__":
    main()