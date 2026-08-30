# Changelog

## 1.1.1

- Update YouTube Music Free to the latest upstream provider for MA 2.10.
- Serialize and retry dependency imports to avoid Python 3.14 import deadlocks.
- Pull YouTube Music Free updates from this patched fork while retaining the previous slot.

## 1.1.0

- Add UI-managed installation and updates through a Home Assistant app repository.
- Discover the Music Assistant container and Python version at runtime.
- Manage YouTube Music Free and private Monochrome independently.
- Retain Current and Previous provider slots with rollback selectors.
