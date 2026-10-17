# Working environment

User direction (2026-10-12): assistant-created hosted QA characters and clans must never appear in public rankings. Use the reserved random QA login namespaces in tio/rating_visibility.py, or explicitly insert custom fixture owners into rating_exclusions(account TEXT PRIMARY KEY) before testing. Remove disposable fixtures after verification. Never delete user-created TestClan or ordinary player accounts as test cleanup.

User direction (2026-09-23): the hosted multiplayer server is the primary gameplay environment. New gameplay features must support multiple real accounts and shared authoritative state. Do not treat local single-player/bot demonstrations as completion.

The user wants updates deployed and verified on the hosting server as part of gameplay changes. Use the existing deployment documentation and inspect the actual remote state before changing it. Preserve hosted accounts and saves; back up the remote database and previous code/config before updates. Never upload local player data over hosted data. Run appropriate automated checks, then verify the hosted service. Clearly distinguish automated checks from validation with real game clients.

Known deployment target from project documentation: root@185.184.42.88, service tio-server, code /opt/tio-emulator, configuration /etc/tio-server/server.toml, data /var/lib/tio-server. SSH authentication must be configured; do not assume connectivity or report deployment without verifying it.
