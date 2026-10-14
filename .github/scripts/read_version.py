"""Print the version ytmusic_free declares, without importing it.

``ytmusic_free/__init__.py`` imports ``music_assistant`` and
``music_assistant_models`` at module scope, and neither is installed in a plain
CI job, so ``import ytmusic_free`` is not available here. Parsing the AST reads
the same assignment the running provider uses, with no dependencies and no
import side effects.

Used by ``.github/workflows/release.yml`` to refuse a tag that disagrees with
the version recorded in the code.
"""

from __future__ import annotations

import ast
import pathlib
import sys

SOURCE = pathlib.Path(__file__).resolve().parents[2] / "ytmusic_free" / "__init__.py"

for node in ast.parse(SOURCE.read_text(encoding="utf-8")).body:
    if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
    ):
        version = ast.literal_eval(node.value)
        if not isinstance(version, str) or not version:
            sys.exit(f"__version__ is not a non-empty string: {version!r}")
        print(version)
        break
else:
    sys.exit(f"{SOURCE} defines no __version__")
