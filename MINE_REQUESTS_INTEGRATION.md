# Native checkpoint requests: integration contract

New runtime files: `server/mine_requests.py`, `tio/protocol/mine_requests.py`,
`config/mine_requests.json`. Add `MineRequests` to the shared hub and call
`init_mine_requests()` in its constructor. Restart intentionally drops pending
requests; there are no funds, inventory holds or saved-player migrations.

- `mine_waiting(owner) -> bool`: include in normal shared busy fences.
- `enqueue_mine_request(owner, town, ticket, role) -> MineRequest`: role 3 defense
  and role 2 raid assistance only. Freeze a `SearchTicket` from the currently
  owned selected squad. The existing first-raider direct entry may remain.
  Enqueue is idempotent for unchanged selections and role.
- `cancel_mine_request(owner) -> bool`: route B019 and call on disconnect and
  forget **before** removing the owner's session. Sends native B01B plus private
  B018 own row with order -1. Cancel never extracts an active battle participant.
- `queue_packets(owner, town) -> (B018, B01A)`: append to B01C/B02C menu replies.
  B01A includes active and waiting role counts. Do not follow it with a second
  player-state packet that resets waiting counts to zero.
- `try_mine_requests(battle) -> tuple[owner, ...]`: call after mine creation,
  after committed help requests and from normal tick. It opens its own
  `mine_unit`, delegates geometry/admission to `join_mine`, then removes the
  request only after that unit commits. **Call outside any outer journal unit**:
  the current journal has no after-commit hook for nested units. Storage and
  battlefield failures propagate to the normal server failure policy; invalid
  applicants get native cancel/error and FIFO advances to the next applicant.

The hub supplies `mine_instances(town)`, `mine_seat(battle, role)`,
`join_mine(battle, owner, ticket, role)`, `mine_unit(battle)`, `busy(session)`,
`put(owner, *packets)`, `lock`, `players`, `battles`, `offline`. `mine_seat` owns
capacity/living-miner checks. Enqueue defends the current checkpoint claim;
admission also checks the battle's frozen claim and current clan membership.
Fresh saved HP, selected actor IDs, levels, inventory ownership, current town,
canonical human identity and all other busy reasons are checked again inside
the admission transaction. Foreign database queues cannot enter or appear in
the recipient's queue view. Historical reward participants cannot reenter via
another character slot.

`battle['mine_help']` uses integer keys 3 and 2, bool values, default false.
The miner (role 1) enables key 3; the first raider (role 2) enables key 2.
Defense requires help even when a battle already exists. A raid entry with no
existing raider needs no help; a second raider requires help. Successful help
admission consumes only the corresponding flag inside the battle transaction.
The root controls native skill28 cast authorization and anytime-without-AP rule.

Native proof: `tools/verify_mine_help_native.py`,
`evidence/mine_help_native.json`. B018 identities are plain u32. Each recipient
gets its **own** owner mapped to `session.probe_character_id`; other owners stay
global shared IDs. Rows omitted for self do not clear the original GUI, hence
the explicit negative-order own row. B028 is a role leaderboard query and must
not be used for help. B02C has no body and is the queue-window query.

Validation: `python -m unittest discover -s tests -p test_mine_requests.py -v`
passes 15 ordinary-save tests. These isolate the mixin and native packet ABI;
they do not claim deployed service or graphical-client gameplay validation.
