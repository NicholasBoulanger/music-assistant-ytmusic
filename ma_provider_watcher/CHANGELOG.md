# Changelog

## 1.1.2

- Update YouTube Music Free to upstream 1.2.3 (October 11, 2026).
- Restore Discover recommendations on MA 2.10 and show more personalized shelves.
- Recover playback when a YouTube stream URL stops serving partway through a track.
- Add cookie-auth notices, corrected video artwork, and provider icons.
- Preserve this fork's serialized package installation, shared MA importer, and bounded Python 3.14 deadlock retries.

## 1.1.1

- Update YouTube Music Free to the latest upstream provider for MA 2.10.
- Serialize and retry dependency imports to avoid Python 3.14 import deadlocks.
- Pull YouTube Music Free updates from this patched fork while retaining the previous slot.

## 1.1.0

- Add UI-managed installation and updates through a Home Assistant app repository.
- Discover the Music Assistant container and Python version at runtime.
- Manage YouTube Music Free and private Monochrome independently.
- Retain Current and Previous provider slots with rollback selectors.
