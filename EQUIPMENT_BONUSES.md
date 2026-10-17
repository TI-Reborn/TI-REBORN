# Equipment bonuses

Sources: original items.cfg / evidence/items_diagnostic.xml and original
TIO manual https://ti.ggeek.ru/files/TIO_manual.pdf pp66,72,74.

| Items | Effect | Activation |
| --- | --- | --- |
| Tank Armor254 / SE256 | +25 Melee proficiency | Human, worn chest suit |
| Freak Helmet262 | +1 sight | Miner, worn head slot |
| Female Exo263 / SE264 | +200 carry capacity | Female, worn chest suit |
| Freak Shield341 | +85 armor | Active weapon hand16 |

The active-hand shield interpretation follows the manual's description of
alternating shield and weapon; a reserve-slot shield does not protect.
No extra dog armor bonus is specified by the manual or original item catalog.
Ordinary armor/enhancements continue through existing ArmorCatalog rules.

Effects are derived from equipped inventory, never written into permanent
training. City roster refreshes reflect changes. Battle sight changes real
visibility, including underground sight (miner6+helmet1); Tank damage uses
effective skill but training uses the unmodified skill. Exo capacity feeds
overload/AP and refreshes on removal. Shield armor affects mitigation and
the existing armor display updates. Backpack items grant no bonuses.

Tests cover species/slots, relog projection without accumulation, helmet
visibility on the ninth cell and removal, both Exo variants/capacity changes,
both Tank variants/base training, actual increased melee damage, shield
protection after weapon swaps. Live VPS/native client check remains pending.

## Install

Close the game. Windows PowerShell:

```powershell
scp C:\TIO-emulator\data\tio-equipment-bonuses.tar.gz C:\TIO-emulator\deploy\install_equipment_bonuses.sh root@185.184.42.88:/root/
```

VPS:

```bash
bash /root/install_equipment_bonuses.sh
```

No client update or database migration is needed. Installer creates a verified
database snapshot and code backup; failed installation restores prior code.
