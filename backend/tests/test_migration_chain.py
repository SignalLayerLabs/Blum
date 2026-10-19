from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text


def test_alembic_revision_ids_fit_postgres_version_column():
    versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    revisions: dict[str, str] = {}

    for migration_path in versions_dir.glob("*.py"):
        module = ast.parse(migration_path.read_text(encoding="utf-8"))
        for node in module.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "revision" for target in node.targets):
                continue
            revision = ast.literal_eval(node.value)
            revisions[migration_path.name] = revision
            break

    oversized = {name: revision for name, revision in revisions.items() if len(revision) > 32}
    assert oversized == {}, f"Revision IDs exceed alembic_version VARCHAR(32): {oversized}"


def test_full_migration_chain_reaches_head_on_sqlite(tmp_path):
    backend_dir = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration-audit.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{database_path}"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite:///{database_path}")
    tables = set(inspect(engine).get_table_names())
    required_tables = {
        "learning_runs",
        "historical_predictions",
        "prediction_outcomes",
        "strategy_memory",
        "model_versions",
        "feedback_loop_audits",
        "live_forward_paper_trades",
        "strategy_factory_runs",
        "strategy_candidate_variants",
        "paper_execution_orders",
        "dashboard_snapshots",
        "brain_runtime_events",
        "background_job_state",
        "forex_trader_cycles",
        "forex_decisions",
        "forex_positions",
        "forex_learning_evidence",
        "forex_strategy_readiness",
        "forex_trader_runtime_state",
        "forex_knowledge_sources",
        "forex_curriculum_assignments",
        "forex_contextual_memory",
        "forex_knowledge_ingestion_runs",
        "forex_policy_states",
        "forex_policy_updates",
        "financial_model_advisors",
        "financial_model_votes",
        "trading_ml_model_versions",
        "trading_ml_training_runs",
        "trading_ml_predictions",
        "deterministic_execution_runs",
        "deterministic_execution_events",
        "execution_parity_comparisons",
        "execution_kernel_state",
        "agent_council_runs",
        "agent_council_turns",
        "agent_council_reflections",
        "ascent_generations",
        "ascent_experiments",
        "ascent_evidence_use",
        "alpha_call_registrations",
        "trading_curriculum_states",
        "trading_curriculum_sources",
        "trading_curriculum_episodes",
    }

    assert required_tables.issubset(tables)
    alpha_indexes = {index['name'] for index in inspect(engine).get_indexes('alpha_call_registrations')}
    assert {'ix_alpha_calls_market_registered', 'ix_alpha_calls_source'}.issubset(alpha_indexes)
    paper_trade_columns = {
        column["name"]
        for column in inspect(engine).get_columns("live_forward_paper_trades")
    }
    assert {
        "side",
        "accounting_status",
        "accounting_version",
        "accounting_recomputed_at",
    }.issubset(paper_trade_columns)
    with engine.connect() as connection:
        assert connection.execute(text("select version_num from alembic_version")).scalar_one() == "0047_trading_curriculum"

    downgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert downgrade.returncode == 0, downgrade.stderr
