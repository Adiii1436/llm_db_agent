from __future__ import annotations

import unittest
from unittest.mock import patch

from langgraph.graph import END

from agent.graph import route_after_research, route_confirmed, route_intent
from agent.nodes import intent, nl_query, research, write_gate
from agent.state import AgentState
from tools.sql import ensure_select_only
from ui.chat import WORKFLOW_LABELS
from ui.query_results_ui import _coerce_rows_for_display


def actions(**overrides: bool) -> dict[str, bool]:
    defaults = {
        "research": False,
        "create_table": False,
        "upsert_table": False,
        "query_table": False,
    }
    defaults.update(overrides)
    return defaults


class WorkflowTests(unittest.TestCase):
    def test_create_table_ui_is_named_extract_table(self) -> None:
        self.assertEqual(WORKFLOW_LABELS["create_table"], "Extract Table")

    def test_extract_table_action_stays_research_only(self) -> None:
        output = intent.run(
            {
                "user_message": "Find pricing plans for Acme and Contoso",
                "requested_actions": actions(create_table=True),
            }
        )

        self.assertEqual(output["intent"], "research")
        next_step = route_after_research(
            AgentState.model_validate(
                {
                    **output,
                    "structured_rows": [{"provider": "Acme", "price": 10}],
                }
            )
        )
        self.assertEqual(next_step, END)

    def test_research_only_returns_text_without_table_display(self) -> None:
        rows = [
            {
                "provider": "Acme",
                "plan_name": "Starter",
                "price_monthly": 10,
                "source_url": "https://example.com/pricing",
            }
        ]
        with (
            patch.object(research, "tavily_extract", return_value={"https://example.com/pricing": "Starter $10"}),
            patch.object(research, "generate_json", return_value={"rows": rows}),
            patch.object(research, "generate_text", return_value="Acme has a Starter plan priced at 10."),
        ):
            output = research.run(
                {
                    "user_message": "Research pricing from https://example.com/pricing",
                    "requested_actions": actions(research=True),
                    "intent": "research",
                }
            )

        self.assertEqual(output["structured_rows"], rows)
        self.assertEqual(output["display_rows"], [])
        self.assertEqual(output["response_to_user"], "Acme has a Starter plan priced at 10.")
        self.assertEqual(output["error"], None)

    def test_extract_table_returns_text_and_table_display(self) -> None:
        rows = [
            {
                "provider": "Acme",
                "plan_name": "Starter",
                "price_monthly": 10,
                "source_url": "https://example.com/pricing",
            }
        ]
        with (
            patch.object(research, "tavily_extract", return_value={"https://example.com/pricing": "Starter $10"}),
            patch.object(research, "generate_json", return_value={"rows": rows}),
            patch.object(research, "generate_text", return_value="Acme has a Starter plan priced at 10."),
        ):
            output = research.run(
                {
                    "user_message": "Extract pricing from https://example.com/pricing",
                    "requested_actions": actions(create_table=True),
                    "intent": "research",
                }
            )

        self.assertEqual(output["structured_rows"], rows)
        self.assertEqual(output["display_rows"], rows)
        self.assertEqual(output["response_to_user"], "Acme has a Starter plan priced at 10.")
        self.assertEqual(output["error"], None)

    def test_extract_table_followup_reuses_previous_research_artifact(self) -> None:
        artifact = {
            "id": "structured_table_1",
            "table_name": "gen_z_food_preferences",
            "rows": [{"preference_category": "Snack", "preference_item": "Fruit and yogurt"}],
            "source_urls": ["https://example.com/gen-z-food"],
        }

        output = intent.run(
            {
                "user_message": "Give the researched data in table format.",
                "session_history": [
                    {
                        "role": "user",
                        "content": "Our team working in zomato marketing, research what genz prefer in food items.",
                    },
                    {"role": "assistant", "content": "Gen Z food preferences are driven by convenience."},
                    {"role": "user", "content": "Give the researched data in table format."},
                ],
                "requested_actions": actions(research=True, create_table=True),
                "structured_artifacts": [artifact],
                "target_table": "gen_z_food_preferences",
            }
        )

        self.assertEqual(output["intent"], "research")
        self.assertEqual(output["structured_rows"], artifact["rows"])
        self.assertEqual(output["display_rows"], artifact["rows"])
        self.assertIn("displayed it as a table", output["response_to_user"])

    def test_upsert_with_research_prompt_routes_to_write_gate(self) -> None:
        output = intent.run(
            {
                "user_message": "Find pricing plans for Acme and Contoso",
                "requested_actions": actions(upsert_table=True),
            }
        )

        state = AgentState.model_validate(output)
        self.assertEqual(state.intent, "write")
        self.assertEqual(route_intent(state), "research")

        researched_state = state.model_copy(update={"structured_rows": [{"provider": "Acme"}]})
        self.assertEqual(route_after_research(researched_state), "check_table")

    def test_upsert_research_returns_text_and_table_display(self) -> None:
        rows = [{"provider": "Acme", "price": 10, "source_url": "https://example.com/pricing"}]
        with (
            patch.object(research, "tavily_extract", return_value={"https://example.com/pricing": "Starter $10"}),
            patch.object(research, "generate_json", return_value={"rows": rows}),
            patch.object(research, "generate_text", return_value="Acme has a Starter plan priced at 10."),
        ):
            output = research.run(
                {
                    "user_message": "Find pricing from https://example.com/pricing and upsert it",
                    "requested_actions": actions(upsert_table=True),
                    "intent": "write",
                }
            )

        self.assertEqual(output["display_rows"], rows)
        self.assertEqual(output["response_to_user"], "Acme has a Starter plan priced at 10.")

    def test_upsert_reuses_previous_extracted_artifact(self) -> None:
        artifact = {
            "id": "structured_table_1",
            "table_name": "competitor_pricing",
            "rows": [{"provider": "Acme", "price": 10}],
            "source_urls": ["https://example.com/pricing"],
        }

        output = intent.run(
            {
                "user_message": "Upsert this data",
                "requested_actions": actions(upsert_table=True),
                "structured_artifacts": [artifact],
                "target_table": "competitor_pricing",
            }
        )

        self.assertEqual(output["intent"], "write")
        self.assertEqual(output["target_table"], "competitor_pricing")
        self.assertEqual(output["structured_rows"], artifact["rows"])
        self.assertEqual(output["display_rows"], artifact["rows"])
        self.assertIn("prepare it for upsert", output["response_to_user"])

    def test_upsert_without_source_has_clear_response(self) -> None:
        output = intent.run(
            {
                "user_message": "Upsert this",
                "requested_actions": actions(upsert_table=True),
            }
        )

        self.assertEqual(output["intent"], "unknown")
        self.assertIn("Upsert needs source data first", output["response_to_user"])

    def test_query_table_lists_saved_tables(self) -> None:
        with patch.object(nl_query, "list_tables", return_value=["foods", "llm_pricing_tiers"]):
            output = nl_query.run({"user_message": "What tables are available?"})

        self.assertEqual(output["intent"], "query")
        self.assertEqual(output["error"], None)
        self.assertEqual(output["display_rows"], [{"table_name": "foods"}, {"table_name": "llm_pricing_tiers"}])

    def test_query_table_executes_select_only_query(self) -> None:
        with (
            patch.object(nl_query, "list_tables", return_value=["foods"]),
            patch.object(nl_query, "table_exists", return_value=True),
            patch.object(
                nl_query,
                "get_columns",
                return_value=[{"table_name": "foods", "column_name": "food_name", "data_type": "text"}],
            ),
            patch.object(
                nl_query,
                "generate_json",
                return_value={"sql": "SELECT food_name FROM foods LIMIT 200", "explanation": "List foods"},
            ),
            patch.object(nl_query, "fetch_all", return_value=[{"food_name": "Apple"}]),
            patch.object(nl_query, "generate_text", return_value="Apple is in the saved table."),
        ):
            output = nl_query.run({"user_message": "List foods", "target_table": "foods"})

        self.assertEqual(output["error"], None)
        self.assertEqual(output["generated_sql"], "SELECT food_name FROM foods LIMIT 200;")
        self.assertEqual(output["display_rows"], [{"food_name": "Apple"}])

    def test_query_sql_guard_allows_select_and_rejects_writes(self) -> None:
        self.assertEqual(
            ensure_select_only("select name from foods where notes = 'DROP TABLE x'"),
            "select name from foods where notes = 'DROP TABLE x';",
        )
        with self.assertRaises(ValueError):
            ensure_select_only("UPDATE foods SET name = 'x'")
        with self.assertRaises(ValueError):
            ensure_select_only("SELECT * FROM foods; DROP TABLE foods")

    def test_table_display_coerces_mixed_complex_cells(self) -> None:
        rows = [
            {"key_elements_or_rules": ["one", "two"], "notes": "list value"},
            {"key_elements_or_rules": {"rule": "three"}, "notes": "dict value"},
            {"key_elements_or_rules": "four", "notes": None},
        ]

        display_rows = _coerce_rows_for_display(rows)

        self.assertEqual(display_rows[0]["key_elements_or_rules"], '["one", "two"]')
        self.assertEqual(display_rows[1]["key_elements_or_rules"], '{"rule": "three"}')
        self.assertEqual(display_rows[2]["key_elements_or_rules"], "four")
        self.assertIsNone(display_rows[2]["notes"])

    def test_write_gate_cancellation_stops_before_db_write(self) -> None:
        state = AgentState(
            intent="write",
            target_table="competitor_pricing",
            proposed_ddl='CREATE TABLE IF NOT EXISTS "competitor_pricing" (id UUID);',
            structured_rows=[{"provider": "Acme"}],
        )

        with patch.object(write_gate, "interrupt", return_value={"user_confirmed": False}):
            output = write_gate.run(state)

        self.assertFalse(output["user_confirmed"])
        self.assertEqual(output["error"], "aborted")
        self.assertEqual(route_confirmed(state.model_copy(update=output)), END)


if __name__ == "__main__":
    unittest.main()
