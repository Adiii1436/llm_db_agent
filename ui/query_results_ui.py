from __future__ import annotations

import html
import json
from typing import Any

import pandas as pd
import streamlit as st


def render_query_results(rows: list[dict], *, max_rows: int | None = None, caption: str | None = None) -> None:
    if not rows:
        st.info("Query returned no results.")
        return
    visible_rows = rows[:max_rows] if max_rows else rows
    df = pd.DataFrame(_coerce_rows_for_display(visible_rows))
    if caption:
        st.caption(caption)
    st.markdown(_rows_table(df.to_dict(orient="records")), unsafe_allow_html=True)
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv,
        file_name="query_results.csv",
        mime="text/csv",
    )


def _coerce_rows_for_display(rows: list[dict]) -> list[dict]:
    return [
        {str(key): _coerce_cell(value) for key, value in row.items()}
        for row in rows
        if isinstance(row, dict)
    ]


def _coerce_cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def _rows_table(rows: list[dict]) -> str:
    if not rows:
        return ""
    columns = list(rows[0].keys())
    header = "".join(f"<th>{html.escape(str(column))}</th>" for column in columns)
    body = "\n".join(
        "<tr>"
        + "".join(f"<td>{html.escape(_display_cell(row.get(column)))}</td>" for column in columns)
        + "</tr>"
        for row in rows
    )
    return f"""
<table class="query-results-table">
  <thead><tr>{header}</tr></thead>
  <tbody>
    {body}
  </tbody>
</table>
"""


def _display_cell(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value)
