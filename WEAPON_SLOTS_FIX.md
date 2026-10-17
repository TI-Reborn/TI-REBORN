# City weapon hand exchange

Original silver.dll drag handler a6641d..a66464 sends weapon swap6D via
8b72c8 when both source and destination controls are hands (16/128).
The previous server routed every 6D to battle turn validation, rejecting
city transfers. Backpack action33 placement already accepted either hand.

The city-only route now exchanges both saved hand slots in one SQLite
transaction scoped to the authenticated account and pet. A single weapon
moves to the empty opposite hand; two weapons exchange places. Counts,
ammunition, enhancements and other opaque item fields are retained. Repeated
exchange restores the original inventory. Battle routing remains unchanged.
The equipment file also retains the tested Tank Armor whole-suit fix.

Validation: 553 unit/integration tests passed, including a real TCP city
swap in both directions with two authenticated accounts. Original native
drag checks passed for both directions and non-hand controls; original 6D
writer passed three actor IDs. Live VPS/client verification remains pending.

Close the game before the brief server restart. In Windows PowerShell:

```powershell
scp C:\TIO-emulator\data\tio-weapon-slots.tar.gz C:\TIO-emulator\deploy\install_weapon_slots_fix.sh root@185.184.42.88:/root/
```

On the VPS:

```bash
bash /root/install_weapon_slots_fix.sh
```

Installer backs up the database and both changed code files, validates Python
syntax and server configuration, and restores old code if installation fails.
No game client update or player database replacement is involved.
