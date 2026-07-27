"""Regression tests for stream quality selection (issue #41).

The provider decides audio quality in exactly one place: the yt-dlp format
selector string in ``_get_stream_format``. Every other test in this suite
monkeypatches that method away, so none of them can see a quality regression.
These tests drive the real ``yt_dlp.YoutubeDL.build_format_selector`` against
synthetic format tables, which needs no network and is fully deterministic.

Issue #41: a bare container name in a yt-dlp selector outranks bitrate. The
old ``"m4a/bestaudio/best"`` therefore picked itag 139 (m4a, 48 kbps) on a free
account, because the 256 kbps m4a (itag 141) is premium-only and the 160 kbps
Opus stream lost to the container preference.
"""

from __future__ import annotations

import asyncio
import types

import pytest

from music_assistant_models.enums import ContentType, MediaType

import ytmusic_free as ytm

yt_dlp = pytest.importorskip("yt_dlp", reason="yt-dlp is needed to test format selection for real")


def _audio(itag: int, ext: str, acodec: str, abr: float) -> dict:
    """Build one audio-only format entry shaped like yt-dlp's."""
    return {
        "format_id": str(itag),
        "ext": ext,
        "acodec": acodec,
        "vcodec": "none",
        "abr": abr,
        "tbr": abr,
        "asr": 48000 if ext == "webm" else 44100,
        "audio_channels": 2,
        "audio_ext": ext,
        "video_ext": "none",
        "protocol": "https",
        "url": f"https://stream.example/{itag}?expire=9999999999",
    }


# What an anonymous/free account is actually offered: itag 141 (256 kbps m4a)
# is premium-only and absent, so 139 is the *only* m4a and it is the worst
# stream in the list. This table is the whole point of issue #41.
FREE_ACCOUNT_FORMATS = [
    _audio(139, "m4a", "mp4a.40.5", 48),
    _audio(249, "webm", "opus", 50),
    _audio(250, "webm", "opus", 70),
    _audio(251, "webm", "opus", 160),
]

PREMIUM_ACCOUNT_FORMATS = [*FREE_ACCOUNT_FORMATS, _audio(141, "m4a", "mp4a.40.2", 256)]


def _stub_yt_dlp_module(formats: list[dict], captured: dict | None = None):
    """Return a fake ``yt_dlp`` module whose extract_info yields ``formats``.

    build_format_selector is delegated to the real yt-dlp, so the selector
    string is evaluated by the same code that runs in production.
    """
    captured = captured if captured is not None else {}
    real = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "simulate": True})

    class _FakeYoutubeDL:
        def __init__(self, opts):
            captured["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            captured["url"] = url
            return {"formats": [dict(f) for f in formats]}

        def build_format_selector(self, spec):
            captured["spec"] = spec
            return real.build_format_selector(spec)

    module = types.ModuleType("yt_dlp")
    module.YoutubeDL = _FakeYoutubeDL
    module.utils = yt_dlp.utils
    return module, captured


def _resolve(provider, formats, *, prefer_quality=True):
    module, captured = _stub_yt_dlp_module(formats)
    provider._yt_dlp_module = module
    provider._prefer_quality = prefer_quality
    result = asyncio.run(provider._get_stream_format("dQw4w9WgXcQ"))
    return result, captured


def test_free_account_never_gets_the_48kbps_stream(provider):
    """The exact regression from issue #41."""
    picked, _ = _resolve(provider, FREE_ACCOUNT_FORMATS)
    assert picked["format_id"] != "139", "issue #41 regression: 48 kbps stream selected"
    assert picked["abr"] >= 128


def test_free_account_gets_the_highest_bitrate_available(provider):
    picked, _ = _resolve(provider, FREE_ACCOUNT_FORMATS)
    assert picked["format_id"] == "251"
    assert picked["abr"] == 160


def test_premium_account_still_gets_the_256kbps_m4a(provider):
    """Ranking by bitrate must not cost anything where a good m4a exists."""
    picked, _ = _resolve(provider, PREMIUM_ACCOUNT_FORMATS)
    assert picked["format_id"] == "141"
    assert picked["abr"] == 256


def test_selector_never_leads_with_a_bare_container(provider):
    """Guard the root cause, not just the symptom.

    yt-dlp treats a bare extension from ``_format_selection_exts`` as "the best
    format in this container", which is resolved before bitrate is considered.
    Leading with one is precisely what produced issue #41, so no branch may do
    it again. The container may still appear as a *filter* (``[ext=m4a]``),
    which applies to bestaudio rather than outranking it.
    """
    selection_exts = {
        ext
        for group in yt_dlp.YoutubeDL._format_selection_exts.values()
        for ext in group
    }
    for prefer in (True, False):
        _, captured = _resolve(provider, FREE_ACCOUNT_FORMATS, prefer_quality=prefer)
        first_leg = captured["spec"].split("/")[0]
        assert first_leg not in selection_exts, (
            f"selector {captured['spec']!r} leads with the bare container "
            f"{first_leg!r}, which yt-dlp resolves ahead of bitrate (issue #41)"
        )


def test_compatibility_mode_picks_the_best_aac_not_the_worst_audio(provider):
    """Disabling the quality toggle asks for AAC, not for the worst stream."""
    picked, captured = _resolve(provider, PREMIUM_ACCOUNT_FORMATS, prefer_quality=False)
    assert "worstaudio" not in captured["spec"]
    assert picked["ext"] == "m4a"
    assert picked["format_id"] == "141", "compatibility mode should take the best AAC"


def test_compatibility_mode_falls_back_when_no_aac_exists(provider):
    """An Opus-only track must still play with the toggle disabled."""
    opus_only = [f for f in FREE_ACCOUNT_FORMATS if f["ext"] == "webm"]
    picked, _ = _resolve(provider, opus_only, prefer_quality=False)
    assert picked["format_id"] == "251"


def test_opus_stream_reports_its_codec_not_an_unknown_container(provider):
    """Music Assistant's ContentType has no WEBM member.

    Handing it the container reports every Opus stream as UNKNOWN, so the codec
    is used whenever the container is not recognised.
    """
    module, _ = _stub_yt_dlp_module(FREE_ACCOUNT_FORMATS)
    provider._yt_dlp_module = module
    provider._prefer_quality = True
    details = asyncio.run(provider.get_stream_details("dQw4w9WgXcQ", MediaType.TRACK))
    assert details.audio_format.content_type == ContentType.OPUS
    assert details.audio_format.content_type != ContentType.UNKNOWN


def test_m4a_stream_still_reports_m4a(provider):
    """The codec fallback must not change the container-known case."""
    module, _ = _stub_yt_dlp_module(PREMIUM_ACCOUNT_FORMATS)
    provider._yt_dlp_module = module
    provider._prefer_quality = False
    details = asyncio.run(provider.get_stream_details("dQw4w9WgXcQ", MediaType.TRACK))
    assert details.audio_format.content_type == ContentType.M4A


def test_stream_details_reports_the_bitrate(provider):
    """Without this the UI shows nothing, which is why #41 went unnoticed."""
    module, _ = _stub_yt_dlp_module(FREE_ACCOUNT_FORMATS)
    provider._yt_dlp_module = module
    provider._prefer_quality = True
    details = asyncio.run(provider.get_stream_details("dQw4w9WgXcQ", MediaType.TRACK))
    assert details.audio_format.bit_rate == 160
    assert details.audio_format.sample_rate == 48000


# ---------------------------------------------------------------------------
# Last-resort fallback, used when the format selector yields nothing.
# ---------------------------------------------------------------------------


def _video_format(itag: int, abr: float | None = None) -> dict:
    """A format with video in it, which the fallback must never consider."""
    fmt = _audio(itag, "mp4", "mp4a.40.2", abr or 999)
    fmt["vcodec"] = "avc1.640028"
    fmt["video_ext"] = "mp4"
    fmt["audio_ext"] = "none"
    return fmt


def _stub_without_working_selector(formats: list[dict]):
    """Fake yt_dlp whose build_format_selector always raises.

    ``_get_stream_format`` swallows selector failures and falls through to its
    manual ranking. That branch is unreachable while the selector works, so it
    had no coverage at all: the bug it contained (trusting yt-dlp's list order
    instead of the bitrate) could not have been caught by any existing test.
    """

    class _FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            return {"formats": [dict(f) for f in formats]}

        def build_format_selector(self, spec):
            raise ValueError("selector unavailable")

    module = types.ModuleType("yt_dlp")
    module.YoutubeDL = _FakeYoutubeDL
    module.utils = yt_dlp.utils
    return module


def _resolve_via_fallback(provider, formats, *, prefer_quality=True):
    provider._yt_dlp_module = _stub_without_working_selector(formats)
    provider._prefer_quality = prefer_quality
    return asyncio.run(provider._get_stream_format("dQw4w9WgXcQ"))


def test_fallback_ranks_by_bitrate_not_by_list_position(provider):
    """The regression guard for the fallback.

    The list is deliberately ordered best-first, the opposite of yt-dlp's
    usual convention. The old ``audio_formats[-1]`` would return the 48 kbps
    stream here, which is issue #41 all over again on a different code path.
    """
    best_first = list(reversed(FREE_ACCOUNT_FORMATS))
    assert best_first[-1]["format_id"] == "139", "fixture must put the worst last"
    picked = _resolve_via_fallback(provider, best_first)
    assert picked["format_id"] == "251"
    assert picked["abr"] == 160


def test_fallback_agrees_with_the_selector(provider):
    """Both paths must call the same format best, or quality silently varies."""
    for formats in (FREE_ACCOUNT_FORMATS, PREMIUM_ACCOUNT_FORMATS):
        for prefer in (True, False):
            via_selector, _ = _resolve(provider, formats, prefer_quality=prefer)
            via_fallback = _resolve_via_fallback(provider, formats, prefer_quality=prefer)
            assert via_selector["format_id"] == via_fallback["format_id"], (
                f"selector picked {via_selector['format_id']} but the fallback "
                f"picked {via_fallback['format_id']} (prefer_quality={prefer})"
            )


def test_fallback_compatibility_mode_prefers_aac(provider):
    picked = _resolve_via_fallback(provider, PREMIUM_ACCOUNT_FORMATS, prefer_quality=False)
    assert picked["format_id"] == "141"


def test_fallback_compatibility_mode_accepts_opus_when_no_aac_exists(provider):
    opus_only = [f for f in FREE_ACCOUNT_FORMATS if f["ext"] == "webm"]
    picked = _resolve_via_fallback(provider, opus_only, prefer_quality=False)
    assert picked["format_id"] == "251"


def test_fallback_ignores_video_formats(provider):
    """A video format's huge tbr must not win the audio ranking."""
    picked = _resolve_via_fallback(provider, [*FREE_ACCOUNT_FORMATS, _video_format(137)])
    assert picked["format_id"] == "251"


def test_fallback_survives_formats_with_no_bitrate(provider):
    """A missing abr must sort last, not raise."""
    nameless = _audio(600, "webm", "opus", 0)
    nameless.pop("abr")
    nameless.pop("tbr")
    picked = _resolve_via_fallback(provider, [nameless, *FREE_ACCOUNT_FORMATS])
    assert picked["format_id"] == "251"

    only_broken = dict(nameless)
    assert _resolve_via_fallback(provider, [only_broken])["format_id"] == "600"


def test_fallback_uses_tbr_when_abr_is_absent(provider):
    """Audio-only formats sometimes report tbr only."""
    tbr_only = _audio(601, "webm", "opus", 320)
    tbr_only.pop("abr")
    picked = _resolve_via_fallback(provider, [*FREE_ACCOUNT_FORMATS, tbr_only])
    assert picked["format_id"] == "601"


def test_fallback_returns_a_video_format_only_as_the_very_last_resort(provider):
    """No audio-only format at all still has to produce something playable."""
    picked = _resolve_via_fallback(provider, [_video_format(137)])
    assert picked["format_id"] == "137"


@pytest.mark.parametrize("prefer_quality", [True, False])
def test_rank_audio_format_tolerates_junk_bitrates(prefer_quality):
    """Unparseable values sort as zero rather than raising mid-playback."""
    junk = {"ext": "webm", "acodec": "opus", "abr": "not-a-number"}
    assert ytm._rank_audio_format(junk, prefer_quality)[1] == 0.0


def test_rank_audio_format_detects_aac_in_a_non_m4a_container():
    """AAC can arrive in an mp4 container, so ext alone is not enough."""
    aac_in_mp4 = {"ext": "mp4", "acodec": "mp4a.40.2", "abr": 128}
    opus = {"ext": "webm", "acodec": "opus", "abr": 160}
    assert ytm._rank_audio_format(aac_in_mp4, False) > ytm._rank_audio_format(opus, False)
    # ...but in quality mode the higher bitrate still wins.
    assert ytm._rank_audio_format(opus, True) > ytm._rank_audio_format(aac_in_mp4, True)


def test_no_player_client_is_pinned(provider):
    """No explicit client list is valid across the supported yt-dlp range.

    android_vr does not exist in 2024.01; android_music was removed by 2026.07,
    where the remaining android/ios clients are PO-token gated and return no
    usable anonymous formats. Pinning any list breaks one end or the other.
    """
    _, captured = _resolve(provider, FREE_ACCOUNT_FORMATS)
    youtube_args = captured["opts"]["extractor_args"]["youtube"]
    assert "player_client" not in youtube_args
