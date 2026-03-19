"""CLI package for twin-runtime.

Re-exports main() and all shared helpers/constants for backward compatibility.
External code can still do ``from twin_runtime.cli import main`` or
``import twin_runtime.cli as cli_mod; cli_mod._CONFIG_DIR``.
"""

from twin_runtime.cli._main import (  # noqa: F401
    TwinNotFoundError,
    _CONFIG_DIR,
    _CONFIG_FILE,
    _STORE_DIR,
    _apply_env,
    _build_registry,
    _get_twin,
    _load_config,
    _mask,
    _require_twin,
    _save_config,
    _twin_parent,
    _write_env,
    main,
)

# Re-export all cmd_* functions so ``from twin_runtime.cli import cmd_reflect`` works
from twin_runtime.cli._setup import cmd_init, cmd_config, cmd_sources  # noqa: F401
from twin_runtime.cli._pipeline import cmd_run, cmd_scan, cmd_compile  # noqa: F401
from twin_runtime.cli._calibration import cmd_evaluate, cmd_reflect, cmd_drift_report  # noqa: F401
from twin_runtime.cli._reporting import cmd_status, cmd_dashboard, cmd_ontology_report  # noqa: F401
from twin_runtime.cli._onboarding import cmd_bootstrap  # noqa: F401
from twin_runtime.cli._comparison import cmd_compare  # noqa: F401
from twin_runtime.cli._skills import cmd_install_skills, cmd_mcp_serve  # noqa: F401
