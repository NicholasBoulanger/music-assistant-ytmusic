"""Offline tests for the pure helpers in the live canary.

The canary itself only runs on a schedule against the real YouTube, so nothing
in an ordinary run exercises its logic. That is fine for the parts that are
just assertions about a live response, but ``_is_bot_check`` decides whether a
failure is reported or swallowed, and getting it wrong is silent in both
directions: too broad and the canary stops reporting real gating, too narrow
and it goes red every night for a reason nobody can act on.

Imported from the live module rather than duplicated, so these pin the code
that actually runs. Importing that module does not touch the network; only its
tests do, and they are deselected here by the ``live`` marker.
"""

from __future__ import annotations

import pytest

from test_live_extraction import _is_bot_check

# Verbatim from the failing run on 2026-08-17, apostrophe included: the real
# message uses U+2019, not an ASCII quote, which is why the matcher avoids that
# part of the sentence entirely.
BOT_CHECK = (
    "ERROR: [youtube] l6USUAIKJls: Sign in to confirm you’re not a bot. "
    "Use --cookies-from-browser or --cookies for the authentication. See "
    "https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp "
    "for how to manually pass cookies."
)


def test_recognises_the_real_bot_check_message():
    assert _is_bot_check(RuntimeError(BOT_CHECK))


def test_recognises_the_ascii_apostrophe_variant():
    """Whichever way the sentence is punctuated, the verdict has to be the same."""
    assert _is_bot_check(RuntimeError(BOT_CHECK.replace("’", "'")))


def test_age_gating_is_not_a_bot_check():
    """The one discrimination that matters, and the easy one to break.

    "Sign in to confirm your age" shares six opening words with the bot check
    and means the opposite thing for this canary: age-gating belongs to the
    content, reproduces from any address, and would be a real finding. A
    matcher loosened to "sign in to confirm" would swallow it.
    """
    assert not _is_bot_check(
        RuntimeError(
            "ERROR: [youtube] l6USUAIKJls: Sign in to confirm your age. "
            "This video may be inappropriate for some users."
        )
    )


@pytest.mark.parametrize(
    "message",
    [
        "ERROR: [youtube] l6USUAIKJls: Video unavailable",
        "ERROR: [youtube] l6USUAIKJls: Private video",
        "ERROR: [youtube] l6USUAIKJls: This video is not available in your country",
        "HTTP Error 403: Forbidden",
        "No formats found for l6USUAIKJls",
        "",
    ],
)
def test_ordinary_failures_are_not_bot_checks(message):
    assert not _is_bot_check(RuntimeError(message))
