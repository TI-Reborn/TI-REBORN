"""Server-controlled monsters, by their client mob ID (base/mobs.udf).

They have no saved account: killing them yields no rank or advisor bonus, and
their equipment is never saved, repaired or worn down.
"""
SICK_MINER = 100
WILD_MINER = 102
INFECTED_DOG = 103  # world encounters and contract maps
MOB_RESOURCES = frozenset((SICK_MINER, WILD_MINER, INFECTED_DOG))
MINE_MUTANTS = frozenset((SICK_MINER, WILD_MINER))
