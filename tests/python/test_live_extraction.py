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

It also fetches bytes. Resolving a URL and playing it are separate failures:
issue #51 was a URL that resolved perfectly every time and then answered the
fetch with 403, because YouTube had put a pre-roll ad in front of the track.
This suite passed green every morning of that outage, because none of it ever
fetched anything. A canary that only checks extraction cannot see a playback
bug, so ``test_live_stream_url_is_fetchable_the_moment_it_is_handed_over``
fetches the first bytes of the URL the provider hands over, immediately, the
same way Music Assistant does.
"""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from music_assistant_models.enums import ContentType, MediaType

import ytmusic_free as ytm
from ytmusic_free import PODCAST_EPISODE_SPLITTER

pytestmark = pytest.mark.live

# Long-lived, extremely well-known videos. Several, so that a single takedown
# or regional block reports as "this one video is gone" rather than as
# "anonymous extraction is broken".
KNOWN_VIDEO_IDS = ("dQw4w9WgXcQ", "kJQP7kiw5Fk", "9bZkp7q19f0")

# The regression from issue #41 was a 48 kbps stream. Anonymous playback is
# normally offered Opus somewhere around 130 to 160 kbps, varying by video,
# region and account. Anything at or above this floor is unambiguously clear of
# the bad stream, with room left for YouTube to shift its tiers.
MIN_ACCEPTABLE_BITRATE = 96

# Enough bytes to prove googlevideo served the media rather than an error page.
PROBE_BYTES = 1024


def _is_bot_check(err: BaseException) -> bool:
    """True when ``err`` is YouTube refusing an anonymous client as a suspected bot.

    Matched on "not a bot" rather than the full sentence. The message wraps a
    video id and two wiki urls that change between releases, and its apostrophe
    is a unicode right single quote, so matching on "you're" fails depending on
    how the text was copied.

    Narrow on purpose, to exclude "Sign in to confirm your age". That shares the
    opening words and means something entirely different: age-gating belongs to
    the content and reproduces from any IP, so it has to keep failing loudly
    rather than skip.
    """
    return "not a bot" in str(err)


def _fetch_range(url: str) -> tuple[int, bytes]:
    """Fetch the first bytes of ``url``. Returns (status, body).

    Deliberately stdlib: the live suite installs nothing beyond what the offline
    one needs, and a Range GET is not worth a dependency. Sends no headers other
    than the range, so a URL that only works with yt-dlp's own headers should
    fail here rather than pass.

    The range is *bounded*, which since 2026-08 is the only kind googlevideo
    answers, and that limits what this probe can prove: it checks the URL is
    valid and serving, not that Music Assistant's fetch of it would succeed.
    It stayed green through the whole bounded-range outage while ffmpeg's
    unbounded fetches answered 403 for every user. The playback-shaped check
    is ``test_live_playback_path_streams_bounded_chunks``, which fetches
    through the provider's own ``get_audio_stream``.
    """
    request = urllib.request.Request(url, headers={"Range": f"bytes=0-{PROBE_BYTES - 1}"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - https url from yt-dlp
        return response.status, response.read(PROBE_BYTES)


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

    # A bot check here is reported rather than skipped, unlike the podcast
    # episode check further down. Music tracks are the provider's core function
    # and are refused far less readily than long-form video, so YouTube turning
    # one away is worth a human look even when the address is the reason.
    if any("not a bot" in failure for failure in failures):
        pytest.fail(
            "YouTube answered anonymous extraction with its bot check for every "
            "known video. On a datacenter address that can mean the runner "
            "rather than the provider, so re-run before changing code; if it "
            "persists, anonymous playback is genuinely gated and users are "
            "affected:\n  " + "\n  ".join(failures)
        )

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


def test_live_stream_url_is_fetchable_the_moment_it_is_handed_over(provider):
    """Issue #51: a URL that resolves cleanly and then 403s on fetch.

    Every other check in this file stops at "yt-dlp returned a url", which is
    why this suite reported green every morning for eight days while playback
    was broken for users. The failure only exists at fetch time, so the only
    way to see it is to fetch.

    YouTube puts a pre-roll ad in front of some tracks and serves a media URL
    that is not valid until the ad window has passed. yt-dlp reports the window
    as ``available_at`` and its own downloader sleeps it out before touching the
    url; the provider has to do the same, because Music Assistant fetches the
    moment it is handed one.

    Fetching immediately is the entire point of this test. Any wait inserted
    between ``get_stream_details`` returning and the fetch below would hide the
    regression exactly the way yt-dlp's sleep hides it.
    """
    video_id, _ = _resolve_first_available(provider)

    provider._yt_dlp_module = None
    provider._prefer_quality = True
    details = asyncio.run(provider.get_stream_details(video_id, MediaType.TRACK))

    try:
        status, body = _fetch_range(details.path)
    except urllib.error.HTTPError as err:
        pytest.fail(
            f"{video_id}: the stream url resolved fine and then answered "
            f"HTTP {err.code} when fetched. This is the issue #51 shape: "
            "Music Assistant would log 'Skipping unplayable item' and the "
            "user would hear nothing. If this is 403, check whether the "
            "resolved format carried an 'available_at' in the future and the "
            "provider failed to wait it out."
        )
    except urllib.error.URLError as err:
        pytest.fail(f"{video_id}: could not reach the stream url at all: {err}")

    assert status in (200, 206), f"{video_id}: unexpected status {status}"
    assert len(body) > 0, (
        f"{video_id}: googlevideo accepted the range request and returned no "
        "bytes, which is not a stream anyone can play"
    )


def test_live_playback_path_streams_bounded_chunks(provider):
    """Fetch through ``get_audio_stream``, the way Music Assistant now plays.

    2026-08-19: googlevideo started refusing any fetch without a *bounded*
    Range header. Extraction stayed green, ``_fetch_range`` stayed green (it
    is bounded), and playback broke for every install at once, because ffmpeg
    only fetches unbounded. The provider now pulls the bytes itself in bounded
    chunks; this walks that exact code path against the real googlevideo, so
    the canary fails when playback fails rather than when a probe that merely
    resembles playback fails.

    Reads a little over two chunks, because the second request is the one
    that would expose a broken continuation (an off-by-one range, a loop that
    never advances, a total parsed wrongly).

    At the PRODUCTION chunk size, deliberately and at the cost of a couple of
    MiB per run. The first version of this test shrank the chunk to 128 KiB
    to save bandwidth, and that is precisely why it passed while production
    403d: googlevideo caps the *size* of a bounded range (1 MiB passed, the
    then-10-MiB production chunk did not), and a canary probing with a
    different size than production proves nothing about production. If the
    chunk size ever needs to change, change it in the provider, never here.
    """
    aiohttp = pytest.importorskip("aiohttp")

    video_id, _ = _resolve_first_available(provider)
    provider._yt_dlp_module = None
    provider._prefer_quality = True
    details = asyncio.run(provider.get_stream_details(video_id, MediaType.TRACK))

    chunk_size = ytm.STREAM_CHUNK_SIZE

    async def _stream_past_the_first_chunk() -> bytes:
        async with aiohttp.ClientSession() as session:
            provider.mass = SimpleNamespace(http_session=session)
            collected = b""
            generator = provider.get_audio_stream(details)
            try:
                async for part in generator:
                    collected += part
                    if len(collected) > 2 * chunk_size:
                        break
            finally:
                await generator.aclose()
            return collected

    try:
        body = asyncio.run(_stream_past_the_first_chunk())
    except Exception as err:  # noqa: BLE001 - the failure text is the deliverable
        pytest.fail(
            f"{video_id}: the provider's own streaming path failed: "
            f"{type(err).__name__}: {err}. This is what a user hears as "
            "'Skipping unplayable item'; the URL probes above passing while "
            "this fails means the enforcement rules changed again."
        )

    assert len(body) > 2 * chunk_size, (
        f"{video_id}: the stream ended after {len(body)} bytes, before the "
        "second chunk completed. Either the track is implausibly short or the "
        "chunk loop stopped advancing."
    )


def test_ytdlp_still_reports_the_preroll_window(provider):
    """The provider's pre-roll wait is only as real as this field.

    ``_preroll_wait_seconds`` reads ``available_at`` with ``.get``, so if
    yt-dlp ever renames or drops it the wait silently becomes a no-op and
    issue #51 comes back with no failing test anywhere. Nothing offline can
    catch that: the unit tests feed the field in by hand.
    """
    video_id, fmt = _resolve_first_available(provider)
    assert "available_at" in fmt, (
        f"{video_id}: yt-dlp no longer reports 'available_at' on formats. The "
        "provider's pre-roll wait now does nothing and tracks behind an ad "
        "will 403 again (issue #51). Check what upstream replaced it with."
    )


def test_compatibility_mode_still_resolves_something_playable(provider):
    """The toggle-off path has to keep working, whatever codec it lands on."""
    video_id, fmt = _resolve_first_available(provider, prefer_quality=False)
    assert fmt.get("url", "").startswith("http"), f"{video_id}: no usable stream url"
    assert fmt.get("vcodec") == "none", f"{video_id}: compatibility mode picked video"


def test_podcasts_still_resolve_anonymously(provider):
    """Issue #52: the whole podcast feature rests on anonymous access.

    Search, show detail and episode detail all answer without an account today.
    If YouTube ever gates any of them behind a sign-in, podcast support stops
    working for most users of this provider and nothing offline would notice,
    because every unit test feeds the parsers hand-written payloads.

    Also pins the two field shapes that surprised us while building it: the
    duration arrives spelled out in words rather than as a clock string, and
    an episode's ``date`` holds a view count rather than a date.
    """
    ytmusicapi = pytest.importorskip("ytmusicapi", reason="needed to reach the podcast endpoints")
    provider._ytmusic = ytmusicapi.YTMusic()

    results = asyncio.run(provider.search("Lex Fridman", [MediaType.PODCAST], limit=3))
    assert results.podcasts, (
        "anonymous podcast search returned nothing. If this is the only podcast "
        "test failing, YouTube may have put shows behind a sign-in."
    )
    podcast = results.podcasts[0]
    assert not podcast.item_id.startswith("MPSP"), (
        f"{podcast.item_id}: the MPSP browse prefix reached Music Assistant. "
        "get_podcast will not accept that id."
    )

    episodes = []

    async def _first_episodes():
        async for episode in provider.get_podcast_episodes(podcast.item_id):
            episodes.append(episode)
            if len(episodes) >= 3:
                break

    asyncio.run(_first_episodes())
    assert episodes, f"{podcast.item_id}: show resolved but yielded no episodes"
    assert all(e.duration > 0 for e in episodes), (
        "an episode came back with no duration. YouTube spells these in words "
        '("3 hr 46 min"); check whether that format changed.'
    )
    assert all(PODCAST_EPISODE_SPLITTER in e.item_id for e in episodes)
    assert all(e.podcast is not None for e in episodes)


def test_live_podcast_episode_is_playable(provider):
    """An episode is an ordinary video id, so the track stream path must carry it.

    Skips rather than fails when YouTube answers with its bot check, because
    that is a property of where the test runs and not of this provider. An
    episode is a regular long-form video, and YouTube applies the check to those
    far more aggressively than to YouTube Music tracks: on a datacenter IP the
    music checks above pass in the same run that this one is refused. Verified
    from a residential connection on 2026-08-17, where the whole live suite
    including this test passes against the same episode CI was refused.

    Failing on it cost the canary five consecutive nights (2026-08-13 to
    2026-08-17, every run since podcast support landed), which is how a check
    stops being read at all.

    This does not blind the canary to a real gating change. If YouTube ever
    demands an account for anonymous playback generally, the music tests above
    fail on the same bot check and the run still goes red. What is given up here
    is only the case where podcast episodes alone become account-only in a way
    that reproduces from every IP, and that would arrive as a user report about
    a feature that demonstrably works today.
    """
    ytmusicapi = pytest.importorskip("ytmusicapi", reason="needed to reach the podcast endpoints")
    provider._ytmusic = ytmusicapi.YTMusic()
    provider._yt_dlp_module = None
    provider._prefer_quality = True

    results = asyncio.run(provider.search("Lex Fridman", [MediaType.PODCAST], limit=3))
    if not results.podcasts:
        pytest.skip("anonymous podcast search returned nothing")

    episode = None

    async def _first_episode():
        nonlocal episode
        async for item in provider.get_podcast_episodes(results.podcasts[0].item_id):
            episode = item
            break

    asyncio.run(_first_episode())
    assert episode is not None

    try:
        details = asyncio.run(
            provider.get_stream_details(episode.item_id, MediaType.PODCAST_EPISODE)
        )
    except Exception as err:  # noqa: BLE001 - narrowed by _is_bot_check below
        if not _is_bot_check(err):
            raise
        pytest.skip(
            f"{episode.item_id}: YouTube answered the episode with its bot "
            "check, so this runner's IP cannot reach episode playback "
            "anonymously. The music checks in this file cover whether "
            "anonymous playback works at all, and they are not skipped; if "
            "they passed in this run, extraction is healthy and this is the "
            "runner's address rather than the provider."
        )

    assert details.item_id == episode.item_id, (
        "StreamDetails must echo the id Music Assistant asked for, or it cannot "
        "match the stream back to the queue item"
    )

    try:
        status, body = _fetch_range(details.path)
    except urllib.error.HTTPError as err:
        pytest.fail(f"episode stream url answered HTTP {err.code}")
    assert status in (200, 206)
    assert len(body) > 0


def test_radio_playlist_still_resolves_tracks(provider):
    """Issue #47: auto-generated mixes resolve through the watch endpoint.

    Song radio is the only member of that family reachable without an account,
    so it stands in for "My Supermix" here. Before the fix this returned zero
    tracks, because ``playlist?list=RD...`` is answered with "This playlist
    type is unviewable" and the failure was discarded silently.

    Only the offline routing is unit-tested. Whether YouTube still answers the
    watch endpoint anonymously is exactly the kind of thing that changes under
    us without a commit here, which is what this suite is for.
    """
    ytmusicapi = pytest.importorskip("ytmusicapi", reason="needed to reach the radio endpoint")
    provider._ytmusic = ytmusicapi.YTMusic()

    tracks = asyncio.run(provider.get_playlist_tracks("RDdQw4w9WgXcQ"))

    assert tracks, (
        "song radio resolved to no tracks. Either the watch endpoint stopped "
        "answering anonymously, or a radio id is being requested as a plain "
        "playlist again (issue #47)."
    )
    assert all(t.item_id for t in tracks)
    # Durations come from a clock string that needs reshaping; without it every
    # track renders as 0:00 in Music Assistant.
    assert any(t.duration for t in tracks), "no track carried a duration"
