# Web to DB Automator

Autonomous research assistant that searches the web with Tavily, extracts
structured rows with Gemini, and writes to Supabase only after a dry-run SQL
confirmation.

## Run

```powershell
python -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

Fill `.env` before using the agent. The LLM layer uses Gemini through
`google-genai` and `GEMINI_API_KEY`.

The app discovers tables and columns directly from Supabase/Postgres at query
time. There are no markdown context files to maintain.

## Safety

- Research-only prompts never write to the database.
- Every schema or data write is shown as SQL first.
- Writes execute only after the confirmation panel is approved.
- Query mode is guarded to allow `SELECT` statements only.
