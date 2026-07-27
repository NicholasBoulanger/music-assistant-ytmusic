"""The upstream Music Assistant facts this provider depends on, in one place.

Two suites assert against this one table:

* ``tests/python_integration/test_models_contract.py`` checks that the real
  ``music_assistant_models`` package still behaves this way.
* ``tests/python/test_stub_matches_contract.py`` checks that the hand-written
  stubs in ``tests/python/conftest.py`` behave the same way.

Pinning both ends to a single table is what closes the blind spot behind
issue #41. The unit suite runs entirely against stubs, so it can only ever be
as correct as they are: an earlier stub invented a ``ContentType.WEBM`` member,
and the whole suite passed green while real Music Assistant reported every
Opus stream as ``"?"``. Asserting the stub against the same table as the real
package makes that class of drift impossible in either direction.

This module is deliberately plain data with no imports. It is not collected as
a test (it does not match ``python_files``); both suites import it by path.
"""

from __future__ import annotations

# Container and codec strings the provider can hand to ``ContentType.try_parse``,
# mapped to the ContentType *member name* it has to come back as. Member names
# rather than members, so the table stays importable without either package.
TRY_PARSE_EXPECTATIONS: dict[str, str] = {
    # yt-dlp reports Opus streams in a WebM container. Upstream has no WEBM
    # member, which is the entire reason ``_get_stream_format`` falls back to
    # the codec when the container does not parse. If this ever stops being
    # UNKNOWN, that fallback can be simplified.
    "webm": "UNKNOWN",
    "opus": "OPUS",
    "m4a": "M4A",
    "mp4": "MP4",
    "vorbis": "VORBIS",
    # yt-dlp spells AAC as "mp4a.40.2" / "mp4a.40.5". Upstream strips the codec
    # profile suffix, so both land on MP4A.
    "mp4a.40.2": "MP4A",
    "mp4a.40.5": "MP4A",
    # yt-dlp uses the literal string "none" for a stream with no audio.
    "none": "UNKNOWN",
    "": "UNKNOWN",
}

# Members the provider references by name. Losing any of these upstream is a
# breaking change we want to hear about from CI, not from a user report.
REQUIRED_CONTENT_TYPE_MEMBERS: tuple[str, ...] = (
    "M4A",
    "MP4",
    "MP4A",
    "AAC",
    "OPUS",
    "VORBIS",
    "UNKNOWN",
)

# Absent upstream, and the codec fallback exists because of it.
FORBIDDEN_CONTENT_TYPE_MEMBERS: tuple[str, ...] = ("WEBM",)

# ``ContentType.UNKNOWN`` is "?" upstream, not "unknown". The provider compares
# against the member rather than the value, but a stub that gets this wrong is
# a signal the stub was written from memory instead of from the source.
UNKNOWN_VALUE = "?"

# ``AudioFormat`` fields the provider assigns. Upstream has more; these are the
# ones whose absence would break playback metadata.
REQUIRED_AUDIO_FORMAT_FIELDS: tuple[str, ...] = (
    "content_type",
    "sample_rate",
    "channels",
    "bit_rate",
)
