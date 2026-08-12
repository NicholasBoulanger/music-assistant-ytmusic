# MA Provider Watcher (Monochrome)

This app keeps the YouTube Music Free and private Monochrome providers installed when Home Assistant recreates the Music Assistant container.

Before starting, turn **Protection mode off**. In Configuration, leave `ma_container` and `python_version` set to `auto`, paste a PAT with read access to `NicholasBoulanger/music-assistant-monochrome`, and select the desired independent update controls.

Each provider retains Current and Previous slots. Select Previous, save, and restart the watcher to roll back. Updates for that provider pause until Current is selected again. Fetch dates and hashes appear in the app logs.
