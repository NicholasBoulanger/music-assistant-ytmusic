# October 13, 2026 provider update

Provider: upstream 1.2.3 (`b1ece38`), with this fork's original Python 3.14
package/import guard retained. The diff against upstream in `__init__.py` consists
only of that guard. Watcher app: 1.1.2.

## Automated checks

- 716 provider tests passed on Python 3.14; 10 network tests were deselected.
- 33 real-model contract tests passed against `music-assistant-models==1.1.205`.
- Alpine 3.20 installer and watcher checks: 96 installer assertions, 32 provider
  installer assertions, and 19 watcher/options/rollback assertions passed, with
  no skips. The watcher test re-execs under Bash to match its generated runtime.
- The startup regression tests cover concurrent instances, MA's shared importer,
  transient and permanent import deadlocks, missing dependencies, older MA, and
  package-install failure with usable dependencies still present.
- CI includes Python 3.14 and runs `tests/verify_server_contract.py` against its
  built MA image, checking recommendation overrides, caching, and auth notices.

Run the offline suites separately so the real-model checks do not use stubs:

```sh
python -m pytest tests/python -q
MA_MODELS_REQUIRED=1 python -m pytest tests/python_integration -q
sh tests/test_install_watcher_addon.sh
sh tests/test_install_provider.sh
bash tests/test_watcher_autoupdate.sh
```

## Actual MA validation

Only the isolated Monochrome lab was used; production was not changed. Its
server was MA 2.10.6 with Python 3.14.7 and models 1.1.205. The installed provider
files matched the updated checkout byte for byte.

An anonymous instance completed MA's real setup flow and loaded without an
error. MA search returned five tracks. Browser Sendspin playback passed with
non-silent PCM, advancing output clock and queue progress, a seek to 90 seconds,
silent stop, resume near the saved position, and a suspended-context negative
control. Cold search took 1.49 seconds.

Two instances initialized concurrently in a separate process using the real
MA config lifecycle and importer; they shared the imported yt-dlp module. The
recommendation hooks produced 20 rows and returned the requested row's items
against real MA classes and cache wrapper using a synthetic home feed.

Personalized Google recommendations and an authenticated cookie session remain
unverified: no production Google cookie or browser profile was read. The stream
URL recovery logic is covered by regression tests; the live playback run does
not establish that YouTube happened to issue a capped URL during that run.
No tokens, cookies, or signed audio URLs are included in these records.
