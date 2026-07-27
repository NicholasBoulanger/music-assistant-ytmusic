"""Regression tests for auto-generated mixes and song radio (issue #47).

YouTube Music's mixes ("My Supermix" ``RDTMAK5uy_...``, "Discover Mix"
``RDCLAK5uy_...``, song radio ``RD<videoId>``) are radio endpoints rather than
stored playlists, and the two things the provider used for ordinary playlists
both fail on them:

* ``https://www.youtube.com/playlist?list=RD...`` is rejected by YouTube with
  "This playlist type is unviewable"
* ``ytmusicapi.get_playlist`` raises a ``KeyError`` parsing the response

Both were verified against the live services. The net effect was that a mix
resolved to zero tracks and playback had nothing to start, while every failure
on the way was discarded without a log line.

These tests pin the routing so the two URL shapes cannot be conflated again,
and pin the reshaping that the watch endpoint's track format requires.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

import ytmusic_free as ytm


# Real ids. The Supermix one is the id reported in issue #47.
SUPERMIX_ID = "RDTMAK5uy_kset8DisdE7LSD4TNjEVvrKRTmG7a56sY"
DISCOVER_MIX_ID = "RDCLAK5uy_lRPRcJlmYzuFTLnZv3S1YvcOEIzZjNCXk"
SONG_RADIO_ID = "RDdQw4w9WgXcQ"
VIDEO_RADIO_ID = "RDAMVMdQw4w9WgXcQ"
STATIC_ID = "PLFgquLnL59alW3xmYiWRaoz0oM3H17Lth"


# ---------------------------------------------------------------------------
# Id classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "playlist_id", [SUPERMIX_ID, DISCOVER_MIX_ID, SONG_RADIO_ID, VIDEO_RADIO_ID]
)
def test_radio_ids_are_recognised(playlist_id):
    assert ytm._is_radio_playlist_id(playlist_id)
    assert ytm._is_radio_playlist_id(f"VL{playlist_id}"), "VL browse prefix must be stripped first"


@pytest.mark.parametrize("playlist_id", [STATIC_ID, f"VL{STATIC_ID}", "OLAK5uy_abc123"])
def test_ordinary_playlist_ids_are_not_treated_as_radio(playlist_id):
    assert not ytm._is_radio_playlist_id(playlist_id)


def test_song_radio_ids_yield_their_seed_video():
    assert ytm._radio_seed_video_id(SONG_RADIO_ID) == "dQw4w9WgXcQ"
    assert ytm._radio_seed_video_id(VIDEO_RADIO_ID) == "dQw4w9WgXcQ"


@pytest.mark.parametrize("playlist_id", [SUPERMIX_ID, DISCOVER_MIX_ID])
def test_curated_mixes_carry_no_seed(playlist_id):
    """The length anchor is what separates these from song radio.

    ``RDTMAK5uy_kset8Dis...`` is far longer than a video id, so treating the
    tail as one would build a URL for a video that does not exist.
    """
    assert ytm._radio_seed_video_id(playlist_id) is None


# ---------------------------------------------------------------------------
# URL routing: the actual bug
# ---------------------------------------------------------------------------


def test_song_radio_uses_the_watch_form_without_help(provider):
    url = provider._yt_playlist_url(SONG_RADIO_ID)
    assert url == f"https://www.youtube.com/watch?v=dQw4w9WgXcQ&list={SONG_RADIO_ID}"


def test_curated_mix_uses_the_watch_form_with_a_supplied_seed(provider):
    url = provider._yt_playlist_url(SUPERMIX_ID, "abcdefghijk")
    assert url == f"https://www.youtube.com/watch?v=abcdefghijk&list={SUPERMIX_ID}"


@pytest.mark.parametrize(
    ("playlist_id", "seed"),
    [
        (SUPERMIX_ID, "abcdefghijk"),
        (DISCOVER_MIX_ID, "abcdefghijk"),
        (SONG_RADIO_ID, None),
        (VIDEO_RADIO_ID, None),
        (f"VL{SONG_RADIO_ID}", None),
    ],
)
def test_no_radio_id_is_ever_requested_as_a_plain_playlist(provider, playlist_id, seed):
    """Guard the root cause rather than one example of it.

    ``playlist?list=RD...`` is the exact request YouTube answers with "This
    playlist type is unviewable", so no radio id that we can build a watch URL
    for may come out in that shape.
    """
    url = provider._yt_playlist_url(playlist_id, seed)
    assert "/playlist?list=" not in url, f"{playlist_id} would be unviewable at {url}"
    assert url.startswith("https://www.youtube.com/watch?v=")


def test_static_playlists_keep_the_plain_form(provider):
    """The watch form must not leak onto ordinary playlists."""
    assert provider._yt_playlist_url(STATIC_ID) == (
        f"https://www.youtube.com/playlist?list={STATIC_ID}"
    )
    # A seed is meaningless here and must be ignored rather than applied.
    assert provider._yt_playlist_url(STATIC_ID, "abcdefghijk") == (
        f"https://www.youtube.com/playlist?list={STATIC_ID}"
    )


def test_vl_prefix_is_stripped_from_the_list_parameter(provider):
    assert provider._yt_playlist_url(f"VL{STATIC_ID}") == (
        f"https://www.youtube.com/playlist?list={STATIC_ID}"
    )


# ---------------------------------------------------------------------------
# Watch-endpoint track reshaping
# ---------------------------------------------------------------------------


def _watch_track(video_id="vid1", length="3:32"):
    """A track shaped the way get_watch_playlist really returns them."""
    return {
        "videoId": video_id,
        "title": "Together Forever",
        "length": length,
        "artists": [{"name": "Rick Astley", "id": "UCwZEU0wAwIyZb4x5G_KJp2w"}],
        # Sizes copied from a real get_watch_playlist response. The largest has
        # to clear _parse_thumbnails' 500px floor or no artwork survives.
        "thumbnail": [
            {"url": "https://i.ytimg.com/vi/x/hq720.jpg?sqp=a", "width": 400, "height": 225},
            {"url": "https://i.ytimg.com/vi/x/hq720.jpg?sqp=b", "width": 800, "height": 450},
            {"url": "https://i.ytimg.com/vi/x/hq720.jpg?sqp=c", "width": 853, "height": 479},
        ],
        "videoType": "MUSIC_VIDEO_TYPE_OMV",
    }


def test_watch_track_duration_is_converted_from_the_clock_string():
    """``_parse_track`` only reads numeric duration keys.

    The watch endpoint reports ``length`` as "3:32", so without the reshaping
    every mix track renders as 0:00.
    """
    normalized = ytm._normalize_watch_track(_watch_track(length="3:32"))
    assert normalized["duration"] == 212


def test_watch_track_artwork_key_is_renamed():
    """Artwork arrives under ``thumbnail``; ``_parse_track`` reads ``thumbnails``."""
    normalized = ytm._normalize_watch_track(_watch_track())
    assert normalized["thumbnails"] == normalized["thumbnail"]


def test_watch_track_reshaping_does_not_clobber_existing_values():
    original = _watch_track()
    original["duration"] = 999
    original["thumbnails"] = [{"url": "keep-me"}]
    normalized = ytm._normalize_watch_track(original)
    assert normalized["duration"] == 999
    assert normalized["thumbnails"] == [{"url": "keep-me"}]


def test_watch_track_reshaping_leaves_the_caller_dict_alone():
    original = _watch_track()
    ytm._normalize_watch_track(original)
    assert "duration" not in original
    assert "thumbnails" not in original


def test_watch_track_survives_a_missing_length():
    broken = _watch_track()
    del broken["length"]
    normalized = ytm._normalize_watch_track(broken)
    assert "duration" not in normalized


def test_parsed_mix_track_ends_up_with_a_duration(provider):
    """End to end through the real parser, which is what MA consumes."""
    track = provider._parse_track(ytm._normalize_watch_track(_watch_track()))
    assert track.duration == 212
    assert track.metadata.images


# ---------------------------------------------------------------------------
# get_playlist_tracks routing
# ---------------------------------------------------------------------------


def test_mix_tracks_come_from_the_watch_endpoint(provider):
    """The fix for issue #47: mixes resolve through get_watch_playlist."""
    mock = MagicMock()
    mock.get_watch_playlist = MagicMock(
        return_value={"tracks": [_watch_track("vid1"), _watch_track("vid2")]}
    )
    mock.get_playlist = MagicMock(side_effect=AssertionError("get_playlist must not be used"))
    provider._ytmusic = mock

    tracks = asyncio.run(provider.get_playlist_tracks(SUPERMIX_ID))

    assert [t.item_id for t in tracks] == ["vid1", "vid2"]
    assert [t.position for t in tracks] == [1, 2]
    assert all(t.duration == 212 for t in tracks)
    kwargs = mock.get_watch_playlist.call_args.kwargs
    assert kwargs["playlistId"] == SUPERMIX_ID
    assert kwargs["limit"] == ytm.RADIO_PLAYLIST_LIMIT


def test_mix_lookup_strips_the_vl_prefix(provider):
    mock = MagicMock()
    mock.get_watch_playlist = MagicMock(return_value={"tracks": [_watch_track("vid1")]})
    provider._ytmusic = mock

    asyncio.run(provider.get_playlist_tracks(f"VL{SUPERMIX_ID}"))

    assert mock.get_watch_playlist.call_args.kwargs["playlistId"] == SUPERMIX_ID


def test_static_playlists_do_not_use_the_watch_endpoint(provider):
    """Ordinary playlists must keep their existing path untouched."""
    mock = MagicMock()
    mock.get_watch_playlist = MagicMock(
        side_effect=AssertionError("watch endpoint must not be used for PL ids")
    )
    mock.get_playlist = MagicMock(
        return_value={
            "trackCount": 1,
            "tracks": [
                {"videoId": "vid1", "title": "Song", "artists": [{"id": "UC1", "name": "A"}]}
            ],
        }
    )
    provider._ytmusic = mock

    tracks = asyncio.run(provider.get_playlist_tracks(STATIC_ID))
    assert [t.item_id for t in tracks] == ["vid1"]


def test_mix_falls_back_when_the_watch_endpoint_returns_nothing(provider):
    """An empty radio result must not strand the playlist.

    Falling through keeps the previous behaviour reachable for anything
    RD-prefixed that happens to read as an ordinary playlist.
    """
    mock = MagicMock()
    mock.get_watch_playlist = MagicMock(return_value={"tracks": []})
    mock.get_playlist = MagicMock(
        return_value={
            "trackCount": 1,
            "tracks": [
                {"videoId": "vid9", "title": "Song", "artists": [{"id": "UC1", "name": "A"}]}
            ],
        }
    )
    provider._ytmusic = mock

    tracks = asyncio.run(provider.get_playlist_tracks(SUPERMIX_ID))
    assert [t.item_id for t in tracks] == ["vid9"]


def test_watch_endpoint_failure_is_logged_not_swallowed(provider, caplog):
    """The silence is half the bug: the reporter saw a stall and an empty log."""
    mock = MagicMock()
    mock.get_watch_playlist = MagicMock(side_effect=KeyError("endpoint"))
    mock.get_playlist = MagicMock(side_effect=KeyError("contents"))
    provider._ytmusic = mock
    provider._get_playlist_tracks_via_ytdlp = _empty_fallback

    with caplog.at_level("WARNING"):
        tracks = asyncio.run(provider.get_playlist_tracks(SUPERMIX_ID))

    assert tracks == []
    messages = [record.getMessage() for record in caplog.records]
    assert any("get_watch_playlist failed" in message for message in messages), (
        f"the failure was discarded silently; log held: {messages!r}"
    )
    assert any(SUPERMIX_ID in message for message in messages)


async def _empty_fallback(_playlist_id, _seed=None):
    return []


def test_ytdlp_extraction_failure_is_logged(provider, caplog):
    """Both swallow sites used to discard the error entirely."""

    class _Boom:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            raise RuntimeError("This playlist type is unviewable")

    import types

    module = types.ModuleType("yt_dlp")
    module.YoutubeDL = _Boom
    provider._yt_dlp_module = module

    with caplog.at_level("WARNING"):
        tracks = asyncio.run(provider._get_playlist_tracks_via_ytdlp(STATIC_ID))

    assert tracks == []
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "unviewable" in joined, f"error was discarded; log held: {joined!r}"
    assert STATIC_ID in joined
