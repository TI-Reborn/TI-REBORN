# Working environment

User direction (2026-10-12): assistant-created hosted QA characters and clans must never appear in public rankings. Use the reserved random QA login namespaces in tio/rating_visibility.py, or explicitly insert custom fixture owners into rating_exclusions(account TEXT PRIMARY KEY) before testing. Remove disposable fixtures after verification. Never delete user-created TestClan or ordinary player accounts as test cleanup.

User direction (2026-09-23): the hosted multiplayer server is the primary gameplay environment. New gameplay features must support multiple real accounts and shared authoritative state. Do not treat local single-player/bot demonstrations as completion.

The user wants updates deployed and verified on the hosting server as part of gameplay changes. Use the existing deployment documentation and inspect the actual remote state before changing it. Preserve hosted accounts and saves; back up the remote database and previous code/config before updates. Never upload local player data over hosted data. Run appropriate automated checks, then verify the hosted service. Clearly distinguish automated checks from validation with real game clients.

Known deployment target from project documentation: root@185.184.42.88, service tio-server, code /opt/tio-emulator, configuration /etc/tio-server/server.toml, data /var/lib/tio-server. SSH authentication must be configured; do not assume connectivity or report deployment without verifying it.

# Development principles

User direction (2026-10-23): these principles are binding for the author and every agent, in any language. Before writing code, understand the single responsibility it serves and where it belongs in the architecture (docs/ARCHITECTURE.md, CONTRIBUTING.md). They apply to new and modified code; do not move existing paths and APIs or mass-reformat existing code outside a dedicated PR.

1. Single responsibility (SRP). A module, class or function has one reason to change. Game rules, data storage, the network protocol, session coordination and presentation are separate responsibilities. Do not create classes where a plain function is enough.
2. Open for extension (OCP). Add new behaviour through new handlers, strategies, interface implementations or data entries rather than growing conditional chains. Introduce abstractions only when actually needed: a simple change in one place is fine if it is clearer and safer.
3. Liskov substitution (LSP). An interface implementation or subclass honours the contract: preconditions, postconditions, errors and behaviour. No "not implemented" stubs or fake results. Incompatible capabilities belong in separate interfaces.
4. Interface segregation (ISP). Small interfaces and clear public APIs. A consumer depends only on what it uses.
5. Dependency inversion (DIP). Pass dependencies explicitly through arguments and constructors. No global mutable state, hidden dependencies or singletons. Make time, randomness, network, files and the database substitutable where tests need it.
6. Single source of truth (DRY). Do not duplicate game rules, formulas, formats or algorithms. Do not merge similar code that has different reasons to change.
7. Simplicity (KISS, YAGNI). Choose the simplest solution that meets the current requirement; no layers or factories "for the future". Prefer the language's standard library; new external dependencies only by owner decision.
8. Composition over inheritance. Use inheritance only for a genuine "is-a" relationship with a shared contract.
9. Layer separation. Rules do not depend on network, HTTP, database or infrastructure. Use-case coordination, storage and adapters for external formats are kept separate. Dependencies point toward the rules.
10. Pure functions. Separate computation from side effects; keep I/O, database, network and logging at the boundaries so logic can be tested without external resources.
11. Readability. Follow the language's style conventions; clear names, short functions, early returns. Do not hide side effects behind unexpected names. Comments explain reasons and constraints, not what the code already says.
12. Explicit errors. The client is untrusted and the server is authoritative: validate input at the boundaries. Do not catch everything without need, swallow errors, or return fake values instead of failing. Change money and items atomically; account for duplicate requests, reconnects and concurrent access. Waits, locks, retries and network operations need timeouts and limits.
13. TDD. Red, green, refactor. For a defect, write the regression test first. Each test checks one concrete behaviour; substitute external dependencies. Multiplayer features are tested with several accounts. Do not replace testing logic with testing mock calls.
14. Types are part of the contract. Type public functions and module boundaries using the language's means. Types do not replace validation of external data.
15. Resources and state. Release files, connections, locks and sockets explicitly and reliably. Shared mutable state only when necessary and under synchronization.
16. Concurrency only when the task needs it. Do not mix concurrency models without a clear boundary. Handle cancellation, timeouts, errors and clean shutdown.
17. Checks before completion. Run the tests and tools adopted for the component. Do not declare a task done if checks were not run or failed. Report separately what automated tests verified, what real game clients verified, and what remains unverified.

## Python server code

- Standard library only; code stays compatible with Python 3.11 (requires-python).
- PEP 8 and type annotations; Protocol, dataclass, Enum, TypedDict where useful. Manage resources with `with`; no mutable default arguments.
- Rules live in tio/, coordination in server/, client packets in tio/protocol/. Do not add new imports of server from tio.
- Concurrency uses threads and selectors; do not introduce asyncio without agreement.
- Tests use unittest in tests/test_<topic>*.py; substitute dependencies with unittest.mock and temporary SQLite databases.
- Checks as in CI: `python tools/check_handoff.py`, `python -m server --check`, `python tools/run_server_checks.py`.
