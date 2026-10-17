# Tank Armor / Tank Armor SE

Tank Armor (254) and SE (256) were excluded by armor_rules because their
client bodypart is complexarmor. Valid level-five mercenaries were rejected
as incompatible before the level check. Enable these two templates in chest
slot 4, retaining catalog level/species checks.

As confirmed by the user, Tank replaces head, chest and legs together.
Equipping any separate helmet, jacket or trousers removes the Tank suit.
Items return to the backpack; weapons remain equipped. Female Exo's existing
chest/legs policy is unchanged. ArmorCatalog now includes Tank's 220 defense.
No database migration or client resource update is required.

Regression tests reproduce the previous rejection for both variants and
both human sexes. Tests cover level five, rejection at level four, dogs,
wrong slots, persistence, all three replacement directions, double-click
toggle, battle equipment projection and total defense without stacked armor.
Native live rendering still requires an in-game check after VPS installation.

## Install

Close the game before installing; the service is briefly restarted.

Windows PowerShell, run separately:

```powershell
scp C:\TIO-emulator\tio\equipment.py root@185.184.42.88:/root/equipment-tank.py
scp C:\TIO-emulator\deploy\install_tank_armor_fix.sh root@185.184.42.88:/root/
```

On the VPS:

```bash
bash /root/install_tank_armor_fix.sh
```

Installer creates a verified pre-update database backup and a unique code
backup. If installation or startup fails, it restores the previous code and
restarts the previously active service. It does not restore or replace live
player data. Only tio/equipment.py is updated.
