"""Tests that lock down the provider manifest contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


MANIFEST_PATH = Path(__file__).resolve().parents[2] / "ytmusic_free" / "manifest.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_required_top_level_fields(manifest):
    for key in ("type", "domain", "name", "description", "codeowners", "requirements"):
        assert key in manifest, f"manifest is missing required key: {key}"


def test_manifest_domain_matches_package_dir(manifest):
    assert manifest["domain"] == "ytmusic_free"
    assert MANIFEST_PATH.parent.name == manifest["domain"]


def test_manifest_type_is_music(manifest):
    assert manifest["type"] == "music"


def test_manifest_codeowners_non_empty(manifest):
    assert isinstance(manifest["codeowners"], list)
    assert manifest["codeowners"], "manifest must list at least one codeowner"


def test_manifest_requirements_pin_known_libs(manifest):
    requirements = manifest["requirements"]
    assert isinstance(requirements, list)
    joined = " ".join(requirements)
    assert "ytmusicapi" in joined
    assert "yt-dlp" in joined
    # duration-parser was dropped once timestamp parsing moved in-house (PR #29);
    # guard against it creeping back as a needless dependency.
    assert "duration-parser" not in joined


def test_manifest_yt_dlp_floor_covers_the_preroll_field(manifest):
    """A fresh install must land on a yt-dlp the pre-roll fix can trust.

    ``available_at`` exists from 2025.08.20 but is a flat +6s on every format
    until 2025.12.08, so the floor has to clear the later date. The provider
    also guards at runtime (``_ytdlp_honours_preroll``), because pip will not
    upgrade an already-satisfied requirement and existing installs keep
    whatever they first resolved. See issue #51.
    """
    import ytmusic_free as ytm

    requirement = next(r for r in manifest["requirements"] if r.startswith("yt-dlp"))
    _, _, floor = requirement.partition(">=")
    assert floor, f"expected a >= floor on yt-dlp, got {requirement!r}"
    # Only the leading numeric segments: a nightly floor carries a trailing
    # ".dev0" marker that is not part of the calendar version.
    parsed = tuple(int(part) for part in floor.split(".")[:3])
    assert parsed >= ytm.MIN_YTDLP_VERSION_FOR_PREROLL, (
        f"manifest allows yt-dlp {floor}, which predates ad-derived "
        "available_at; a fresh install would wait 6s before every track"
    )


def test_manifest_yt_dlp_requirement_is_the_runtime_requirement(manifest):
    """One floor, stated once.

    ``_install_packages`` is what actually enforces the floor (Music
    Assistant skips manifest requirements without ``==``), but the manifest
    is what documentation and fresh installs read. If the two ever disagree,
    one of them is lying about which yt-dlp the provider needs; since the
    android_vr shutdown that difference is the whole difference between
    playing and not playing. See yt-dlp/yt-dlp#17461.
    """
    import ytmusic_free as ytm

    requirement = next(r for r in manifest["requirements"] if r.startswith("yt-dlp"))
    assert requirement == ytm.MIN_YTDLP_REQUIREMENT


def test_manifest_documentation_url_present(manifest):
    assert manifest.get("documentation", "").startswith("https://")


def test_manifest_declares_multi_instance(manifest):
    # Identity check, not truthiness: Music Assistant reads this straight into
    # ProviderManifest, and the string "true" would be just as truthy in a test
    # while meaning nothing to the config flow. See issue #40.
    assert manifest["multi_instance"] is True


# ---------------------------------------------------------------------------
# Versioning (issue #68)
# ---------------------------------------------------------------------------


def test_version_is_semver():
    """The release workflow compares the tag to this string, so it must parse.

    A tag is rejected unless it is exactly "v" + this value, which is what stops
    a release and the code inside it claiming different numbers.
    """
    import re

    import ytmusic_free as ytm

    assert re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?", ytm.__version__), (
        f"__version__ must be semver, got {ytm.__version__!r}"
    )


def test_manifest_declares_no_version_key(manifest):
    """One source of truth, and the manifest is not it.

    ProviderManifest has no version field and mashumaro drops unknown keys, so a
    copy here would be invisible to Music Assistant while still being free to
    drift away from ytmusic_free.__version__.
    """
    assert "version" not in manifest


def test_manifest_stage_is_a_known_provider_stage(manifest):
    """Mirrors music_assistant_models.enums.ProviderStage.

    A typo parses fine as JSON and then fails inside Music Assistant at load
    time, which is a long way from here.
    """
    assert manifest["stage"] in {
        "alpha",
        "beta",
        "stable",
        "experimental",
        "unmaintained",
        "deprecated",
    }


def test_the_release_helper_reads_the_same_version():
    """The workflow gate must agree with the module it is gating.

    read_version.py parses the AST instead of importing, because ytmusic_free
    imports the music_assistant server package at module scope and that is not
    installed in a plain CI job. This pins the two readings together, so moving
    or reformatting __version__ cannot silently break the release gate.
    """
    import subprocess
    import sys

    import ytmusic_free as ytm

    helper = MANIFEST_PATH.parents[1] / ".github" / "scripts" / "read_version.py"
    result = subprocess.run(
        [sys.executable, str(helper)], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ytm.__version__
