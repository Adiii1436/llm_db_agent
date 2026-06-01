$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
& "$Root\.venv\Scripts\python.exe" -m streamlit run "$Root\app.py" --server.headless=true --server.port=8501 --browser.gatherUsageStats=false
