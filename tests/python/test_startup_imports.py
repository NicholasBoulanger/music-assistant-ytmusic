"""Keep this fork's Python 3.14 startup protection through upstream updates."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import ytmusic_free as ytm


def test_concurrent_instances_serialize_installation_and_use_ma_importer(provider, monkeypatch):
    async def run():
        monkeypatch.setattr(ytm, "_PACKAGE_SETUP_LOCK", asyncio.Lock())
        other = ytm.YoutubeMusicFreeProvider(None, None, None)
        active = peak = 0
        imported = []
        modules = {name: SimpleNamespace(name=name) for name in ("requests", "yt_dlp", "ytmusicapi")}

        async def install(package):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1

        async def shared_import(name):
            imported.append(name)
            await asyncio.sleep(0)
            return modules[name]

        monkeypatch.setattr(ytm, "install_package", install)
        monkeypatch.setattr(ytm.mass_util, "import_module_in_thread", shared_import, raising=False)
        await asyncio.gather(provider._install_packages(), other._install_packages())
        assert peak == 1
        assert imported == ["requests", "yt_dlp", "ytmusicapi"] * 2
        assert provider._yt_dlp_module is other._yt_dlp_module is modules["yt_dlp"]

    asyncio.run(run())


@pytest.mark.parametrize("eventually_succeeds", [True, False])
def test_python_import_deadlock_is_retried_but_bounded(provider, monkeypatch, eventually_succeeds):
    async def run():
        monkeypatch.setattr(ytm, "_PACKAGE_SETUP_LOCK", asyncio.Lock())
        deadlock = type("_DeadlockError", (Exception,), {})
        failures = 2 if eventually_succeeds else ytm.PACKAGE_IMPORT_ATTEMPTS
        importer = AsyncMock(side_effect=[deadlock() for _ in range(failures)] + [SimpleNamespace()] * 3)
        monkeypatch.setattr(ytm, "install_package", AsyncMock())
        monkeypatch.setattr(ytm.mass_util, "import_module_in_thread", importer, raising=False)
        monkeypatch.setattr(ytm.asyncio, "sleep", AsyncMock())
        if eventually_succeeds:
            await provider._install_packages()
            assert importer.await_count == failures + 3
        else:
            with pytest.raises(ytm.SetupFailedError, match="requests failed to import"):
                await provider._install_packages()
            assert importer.await_count == ytm.PACKAGE_IMPORT_ATTEMPTS

    asyncio.run(run())


def test_missing_dependency_is_not_retried_as_an_import_deadlock(provider, monkeypatch):
    importer = AsyncMock(side_effect=ModuleNotFoundError("dependency unavailable"))
    monkeypatch.setattr(ytm, "_PACKAGE_SETUP_LOCK", asyncio.Lock())
    monkeypatch.setattr(ytm, "install_package", AsyncMock())
    monkeypatch.setattr(ytm.mass_util, "import_module_in_thread", importer, raising=False)
    with pytest.raises(ytm.SetupFailedError, match="requests failed to import"):
        asyncio.run(provider._install_packages())
    assert importer.await_count == 1


def test_older_ma_uses_synchronous_imports_and_survives_package_update_failure(provider, monkeypatch):
    imported = []
    modules = {name: SimpleNamespace(name=name) for name in ("requests", "yt_dlp", "ytmusicapi")}

    def direct_import(name):
        imported.append(name)
        return modules[name]

    monkeypatch.setattr(ytm, "_PACKAGE_SETUP_LOCK", asyncio.Lock())
    monkeypatch.delattr(ytm.mass_util, "import_module_in_thread", raising=False)
    monkeypatch.setattr(ytm, "install_package", AsyncMock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr(ytm.importlib, "import_module", direct_import)
    asyncio.run(provider._install_packages())
    assert imported == ["requests", "yt_dlp", "ytmusicapi"]
    assert provider._yt_dlp_module is modules["yt_dlp"]
