"""Live smoke test: can we still resolve an audio stream anonymously today?

Deselected by default via the ``live`` marker in ``pytest.ini``, because it
reaches out to the real YouTube. The scheduled ``live-extraction`` workflow
re-selects it with ``-m live``.

No offline test can catch what this targets. Every other test feeds synthetic
format tables to the selector, so the whole suite stays green even if YouTube
stops serving usable formats to anonymous clients entirely. That is not a
hypothetical failure mode: it is exactly what happened to the ``android_music``
client this provider used to pin, and it surfaced only when a user reported it
(issue #41). Now that no client is pinned at all, the provider's behaviour is
inherited from yt-dlp's defaults, so an upstream change can silently alter what
users get without a single line of this repo changing.

This drives the real ``_get_stream_format``, so it exercises the production
``ydl_opts`` and the production selector string rather than a copy of them.
"""

from __future__ import annotations

import asyncio

import pytest

from music_assistant_models.enums import ContentType, MediaType

pytestmark = pytest.mark.live

# Long-lived, extremely well-known videos. Several, so that a single takedown
# or regional block reports as "this one video is gone" rather than as
# "anonymous extraction is broken".
KNOWN_VIDEO_IDS = ("dQw4w9WgXcQ", "kJQP7kiw5Fk", "9bZkp7q19f0")

# The regression from issue #41 was a 48 kbps stream. A free account is offered
# Opus at ~160 kbps. Anything at or above this is unambiguously not the bad
# stream, with room for YouTube to change its tiers.
MIN_ACCEPTABLE_BITRATE = 96


def _resolve_first_available(provider, *, prefer_quality=True):
    """Return (video_id, format) for the first id that resolves.

    Fails only when every id fails, which is the signal that anonymous
    extraction itself is broken rather than one video being unavailable.
    """
    provider._yt_dlp_module = None  # force the real yt_dlp import
    provider._prefer_quality = prefer_quality
    failures = []
    for video_id in KNOWN_VIDEO_IDS:
        try:
            fmt = asyncio.run(provider._get_stream_format(video_id))
        except Exception as err:  # noqa: BLE001 - any failure is a data point
            failures.append(f"{video_id}: {type(err).__name__}: {err}")
            continue
        if fmt:
            return video_id, fmt
        failures.append(f"{video_id}: selector returned no format")

    pytest.fail(
        "anonymous extraction failed for every known video, which usually means "
        "yt-dlp's default clients now need a PO token or the extractor is "
        "broken:\n  " + "\n  ".join(failures)
    )


def test_anonymous_extraction_still_yields_an_audio_stream(provider):
    video_id, fmt = _resolve_first_available(provider)
    assert fmt.get("url", "").startswith("http"), f"{video_id}: no usable stream url"
    assert fmt.get("vcodec") == "none", (
        f"{video_id}: resolved a format with video in it "
        f"(vcodec={fmt.get('vcodec')!r}), which wastes bandwidth on an audio "
        "provider and suggests no audio-only format was offered"
    )


def test_live_stream_is_not_the_48kbps_regression(provider):
    """The issue #41 guard, against the real API rather than a fixture."""
    video_id, fmt = _resolve_first_available(provider)
    bitrate = fmt.get("abr") or fmt.get("tbr")
    assert bitrate is not None, f"{video_id}: yt-dlp reported no bitrate at all"
    assert bitrate >= MIN_ACCEPTABLE_BITRATE, (
        f"{video_id}: resolved {bitrate} kbps (format {fmt.get('format_id')}), "
        f"below the {MIN_ACCEPTABLE_BITRATE} kbps floor. Issue #41 was exactly "
        "this: the selector quietly picking a 48 kbps stream."
    )


def test_live_stream_details_report_a_usable_content_type(provider):
    """A stream MA reports as "?" is the symptom the codec fallback fixed."""
    provider._yt_dlp_module = None
    provider._prefer_quality = True
    video_id, _ = _resolve_first_available(provider)

    provider._yt_dlp_module = None
    provider._prefer_quality = True
    details = asyncio.run(provider.get_stream_details(video_id, MediaType.TRACK))

    assert details.audio_format.content_type != ContentType.UNKNOWN, (
        f"{video_id}: Music Assistant would show this stream as '?'. Check "
        "whether yt-dlp is reporting a container ContentType does not know and "
        "whether the acodec fallback still covers it."
    )
    assert details.audio_format.bit_rate, f"{video_id}: no bitrate reached StreamDetails"
    assert details.path.startswith("http")


def test_compatibility_mode_still_resolves_something_playable(provider):
    """The toggle-off path has to keep working, whatever codec it lands on."""
    video_id, fmt = _resolve_first_available(provider, prefer_quality=False)
    assert fmt.get("url", "").startswith("http"), f"{video_id}: no usable stream url"
    assert fmt.get("vcodec") == "none", f"{video_id}: compatibility mode picked video"
