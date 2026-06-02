# Web to DB Automator

Turn web research into clean database rows with a human review step before anything is written.

Web to DB Automator is a Streamlit app powered by LangGraph. It can research a topic, extract structured data, preview table-shaped results, generate safe SQL, and upsert approved rows into Supabase/Postgres.

## Features

- Research the web with Tavily and summarize findings.
- Extract structured rows from web content using Gemini.
- Preview extracted tables before saving.
- Create or update Supabase tables from generated SQL.
- Require confirmation before schema or data writes.
- Query saved tables with SELECT-only SQL protection.
- Track write activity in an audit log.

## Tech Stack

- **UI:** Streamlit
- **Agent workflow:** LangGraph
- **LLM:** Gemini via `google-genai`
- **Web research:** Tavily
- **Database:** Supabase/Postgres
- **Data handling:** pandas, psycopg2, sqlparse

## Getting Started

### 1. Create a virtual environment

```powershell
python -m venv .venv
. .venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash

TAVILY_API_KEY=your_tavily_api_key

SUPABASE_URL=your_supabase_project_url
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
SUPABASE_DB_HOST=your_database_host
SUPABASE_DB_PORT=5432
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres
SUPABASE_DB_PASSWORD=your_database_password
SUPABASE_DB_SSLMODE=require
```

`GEMINI_MODEL`, `SUPABASE_DB_PORT`, `SUPABASE_DB_NAME`, `SUPABASE_DB_USER`, and `SUPABASE_DB_SSLMODE` have defaults, but keeping them explicit makes local setup easier to inspect.

### 4. Run the app

```powershell
streamlit run app.py
```

Then open the local Streamlit URL shown in the terminal.

## How It Works

The app starts in chat mode with workflow toggles:

- **Research:** search and summarize information without saving rows.
- **Extract Table:** research and return structured rows for review.
- **Upsert Table:** prepare extracted rows for database insertion.
- **Query Table:** ask questions about saved tables.

For writes, the agent first checks the target table, proposes schema changes when needed, shows the SQL preview, and only executes after confirmation.

## Safety Model

- Research-only requests never write to the database.
- Schema and data writes are previewed as SQL first.
- Writes require explicit approval in the UI.
- Query mode accepts generated `SELECT` statements only.
- Write operations are recorded in `agent_audit_log`.

## Tests

```powershell
python -m unittest
```

## Project Structure

```text
agent/      LangGraph state, routing, and workflow nodes
tools/      Gemini, Tavily, Supabase, and SQL helpers
ui/         Streamlit screens and interaction components
tests/      Workflow and safety tests
app.py      Streamlit entrypoint
```

