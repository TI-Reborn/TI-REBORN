# Gameplay change invariants

Game rules and storage belong in `tio/`, session/hub coordination in `server/`, and bounded binary parsing in `tio/protocol/`. `tools/loopback_exchange.py` is a production transport dependency. Do not move APIs or reformat unrelated modules as part of a defect fix.

Use descriptive Python names, public boundary type annotations, explicit domain rejections and short operations. Parse and validate untrusted IDs/counts/options before mutation. A known rejection returns its native error result without closing a healthy connection; an unexpected programming/storage failure must not be disguised as a normal player refusal.

A new item needs one verified template identity, original metadata/provenance, explicit effect/policy, native request route, display projection and server enforcement. A medkit presentation class does not imply healing: boosters and temporary capacity injections have separate effects. Never infer protection, equipment conflict or business rules from a translated item name. Where original restrictions are unknown, document that boundary and do not grant extra operations by default.

Keep base stats separate from derived level/perk/equipment effects. Use the same authoritative calculation for acceptance, combat/AP and outward stats. Exo/Tank coverage is one slot-conflict rule. Capacity uses base/perks plus current equipped bonuses exactly once; prospective item mass comes from the item catalog. Ordinary and SE failure outcomes differ explicitly while preserving the same inventory transaction contract.

Authenticate logins separately from selected save owners and combat actor IDs. Every mutation must verify the owned recipient. Character deletion is retirement: never reuse an archived owner key, wallet, inventory or immutable receipt for a new character. Additive migrations preserve existing rows; test old saves, repeated application and rollback. Handle shared obligations before retirement rather than silently orphaning another account's property.

One item/money/roster action is one SQL transaction under the applicable hub lock. Prepare outward packets before committing where feasible; send success only after commit. Keep CAS checks, duplicate/reconnect protection, bounded waits and resource cleanup. Legacy packets without action sequence numbers require documented bounded repeat handling; do not claim perfect idempotency across ambiguous new UI intentions.

For a defect, record a failing reproduction before changing behavior. Test exact limits, one below/above, fully/partially spent items, success/refusal/SQL failure, retry/reconnect, both equipment directions and at least two accounts sharing a database. Compare the affected gameplay outcomes, not just helper call counts. Add portable regressions to `tools/run_server_checks.py` and run preflight and `tools/check_handoff.py`.

Reports distinguish local unit tests, actual TCP/TLS protocol clients, staged hosted services and graphical clients. Do not call a gameplay fix deployed until the real service/code hashes are verified. Back up remote database and previous code/config, preserve unrelated rows, use reserved/excluded QA namespaces and remove only owned fixtures. Do not restart over retained battles or restore stale player data as a code rollback.
