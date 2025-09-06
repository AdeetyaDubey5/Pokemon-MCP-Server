# battle_simulator.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import random

from pokemon_data import fetch_json, _cache  # reuse cache and fetch_json (same AsyncClient)
# Note: importing fetch_json allows reuse of same http client and cache

router = APIRouter()

POKEAPI_BASE = "https://pokeapi.co/api/v2"

# ----- Request / Response models -----
class BattleRequest(BaseModel):
    attacker: str              # name or id
    defender: str              # name or id
    attacker_moves: Optional[List[str]] = None
    defender_moves: Optional[List[str]] = None
    level: Optional[int] = 50
    max_turns: Optional[int] = 200
    random_seed: Optional[int] = None

class BattleOutcome(BaseModel):
    winner: Optional[str]
    turns: int
    log: List[str]

# ----- Status constants -----
class Status:
    NONE = None
    PARALYSIS = "paralysis"
    BURN = "burn"
    POISON = "poison"

# ----- Helpers to load pokemon/move/type chart -----
_type_chart_cache = _cache  # reuse same cache for simplicity under key "type_chart"

async def get_pokemon_data(name_or_id: str) -> Dict[str, Any]:
    url = f"{POKEAPI_BASE}/pokemon/{name_or_id.lower()}"
    p = await fetch_json(url)
    stats = {s['stat']['name']: s['base_stat'] for s in p['stats']}
    types = [t['type']['name'] for t in p['types']]
    moves = [{"name": m['move']['name'], "url": m['move']['url']} for m in p['moves']]
    species = await fetch_json(p['species']['url'])
    evo_chain = []
    if species.get('evolution_chain'):
        evo = await fetch_json(species['evolution_chain']['url'])
        def flatten(chain):
            res = [chain['species']['name']]
            for child in chain.get('evolves_to', []):
                res.extend(flatten(child))
            return res
        evo_chain = flatten(evo['chain'])
    return {
        "id": p['id'],
        "name": p['name'],
        "stats": stats,
        "types": types,
        "moves": moves,
        "species_url": p['species']['url'],
        "sprite": p['sprites']['front_default'],
    }

async def get_move_data(name_or_id: str) -> Dict[str, Any]:
    url = f"{POKEAPI_BASE}/move/{name_or_id.lower()}"
    m = await fetch_json(url)
    return {
        "id": m['id'],
        "name": m['name'],
        "power": m['power'],
        "pp": m['pp'],
        "accuracy": m['accuracy'],
        "priority": m['priority'],
        "type": m['type']['name'],
        "damage_class": m['damage_class']['name'] if m.get('damage_class') else None,
        "effect_entries": m.get('effect_entries', []),
        "effect_chance": m.get('effect_chance', None),
    }

async def build_type_chart() -> Dict[str, Dict[str, float]]:
    if "type_chart" in _type_chart_cache:
        return _type_chart_cache["type_chart"]
    chart: Dict[str, Dict[str, float]] = {}
    types_list = (await fetch_json(f"{POKEAPI_BASE}/type"))['results']
    for t in types_list:
        try:
            tdata = await fetch_json(t['url'])
        except Exception:
            continue
        atk = tdata.get('name')
        chart.setdefault(atk, {})
        dr = tdata.get('damage_relations', {})
        double = [x['name'] for x in dr.get('double_damage_to', [])]
        half = [x['name'] for x in dr.get('half_damage_to', [])]
        zero = [x['name'] for x in dr.get('no_damage_to', [])]
        for d in types_list:
            chart[atk][d['name']] = 1.0
        for d in double:
            chart[atk][d] = 2.0
        for d in half:
            chart[atk][d] = 0.5
        for d in zero:
            chart[atk][d] = 0.0
    _type_chart_cache["type_chart"] = chart
    return chart

# ----- Stat / damage helpers -----
def compute_hp_from_base(base_hp: int, level: int) -> int:
    return max(1, int(((2 * base_hp + 31) * level) / 100 + level + 10))

def stat_at_level(base: int, level: int) -> int:
    return max(1, int(((2 * base + 31) * level) / 100 + 5))

def calc_damage(level:int, power:int, attack:float, defense:float, modifier:float) -> int:
    base = (((2 * level) / 5 + 2) * power * (attack / max(1, defense))) / 50 + 2
    rand = random.uniform(0.85, 1.0)
    dmg = int(base * modifier * rand)
    return max(1, dmg)

# ----- select move (prefer provided, else pick a damaging move) -----
async def select_move(poke: Dict[str,Any], provided: Optional[List[str]]):
    if provided:
        for name in provided:
            try:
                mv = await get_move_data(name)
                return mv
            except Exception:
                continue
    # fallback: probe first N moves and pick highest power damaging
    candidates = []
    for mv in poke['moves'][:40]:
        try:
            md = await get_move_data(mv['name'])
            if md['power'] and md['damage_class'] in ("physical","special"):
                candidates.append(md)
        except Exception:
            continue
    if candidates:
        candidates.sort(key=lambda x: (x['power'] or 0), reverse=True)
        return candidates[0]
    return {"name":"struggle","power":50,"accuracy":100,"type":poke['types'][0],"damage_class":"physical","effect_chance":None,"effect_entries":[]}

# ----- attempt to apply status from move (checks effect_entries text & effect_chance) -----
def detect_status_from_move(move: Dict[str,Any]) -> Optional[str]:
    # check text in effect_entries for keywords
    texts = " ".join([e.get('effect','') + " " + e.get('short_effect','') for e in move.get('effect_entries',[])])
    t = texts.lower()
    if "paraly" in t or "paralys" in t:
        return Status.PARALYSIS
    if "burn" in t:
        return Status.BURN
    if "poison" in t:
        return Status.POISON
    return None

async def apply_status_chance(move: Dict[str,Any], target_status: Optional[str]) -> Optional[str]:
    # Returns new status for target (if applied) else returns existing
    # If move has effect_chance and mentions a status, roll it.
    status = detect_status_from_move(move)
    if status is None:
        return target_status
    chance = move.get('effect_chance') or 0
    if chance > 0 and random.randint(1,100) <= chance:
        return status
    return target_status

# ----- main simulator endpoint -----
@router.post("/simulate", response_model=BattleOutcome)
async def simulate_battle(req: BattleRequest):
    if req.random_seed is not None:
        random.seed(req.random_seed)

    # load pokes concurrently
    attacker_data, defender_data = await asyncio.gather(
        get_pokemon_data(req.attacker),
        get_pokemon_data(req.defender)
    )
    type_chart = await build_type_chart()

    L = req.level or 50
    atk_hp = compute_hp_from_base(attacker_data['stats'].get('hp', 10), L)
    def_hp = compute_hp_from_base(defender_data['stats'].get('hp', 10), L)
    atk_curr, def_curr = atk_hp, def_hp

    # derived stats at level
    atk_attack = stat_at_level(attacker_data['stats'].get('attack',10), L)
    atk_sp_atk = stat_at_level(attacker_data['stats'].get('special-attack',10), L)
    atk_speed = stat_at_level(attacker_data['stats'].get('speed',10), L)

    def_attack = stat_at_level(defender_data['stats'].get('attack',10), L)
    def_sp_atk = stat_at_level(defender_data['stats'].get('special-attack',10), L)
    def_speed = stat_at_level(defender_data['stats'].get('speed',10), L)

    # choose moves
    atk_move = await select_move(attacker_data, req.attacker_moves)
    def_move = await select_move(defender_data, req.defender_moves)

    # statuses start none
    atk_status: Optional[str] = Status.NONE
    def_status: Optional[str] = Status.NONE

    log = []
    turn = 0

    def type_multiplier(move_type: str, target_types: List[str]) -> float:
        mult = 1.0
        for t in target_types:
            mult *= type_chart.get(move_type, {}).get(t, 1.0)
        return mult

    def hits(accuracy: Optional[int]) -> bool:
        if accuracy is None:
            return True
        return random.randint(1,100) <= max(1, accuracy)

    # run loop
    while turn < (req.max_turns or 200) and atk_curr > 0 and def_curr > 0:
        turn += 1
        log.append(f"-- Turn {turn} --")

        # effective speed accounting for paralysis
        atk_eff_spd = atk_speed * (0.5 if atk_status == Status.PARALYSIS else 1.0)
        def_eff_spd = def_speed * (0.5 if def_status == Status.PARALYSIS else 1.0)
        first_attacker = atk_eff_spd >= def_eff_spd

        # two actions per turn
        for actor in ("attacker" if first_attacker else "defender",
                      "defender" if first_attacker else "attacker"):
            if atk_curr <= 0 or def_curr <= 0:
                break
            if actor == "attacker":
                user_name = attacker_data['name']
                target_name = defender_data['name']
                move = atk_move
                user_status = atk_status
                target_status = def_status
                # check paralysis skip
                if user_status == Status.PARALYSIS and random.random() < 0.25:
                    log.append(f"{user_name} is paralyzed and can't move!")
                    continue
                # accuracy
                if not hits(move.get('accuracy')):
                    log.append(f"{user_name} used {move['name']} but it missed!")
                    continue
                # compute damage
                power = move.get('power') or 0
                if power > 0:
                    attack_stat = atk_attack if move['damage_class']=='physical' else atk_sp_atk
                    defense_stat = def_attack if move['damage_class']=='physical' else def_sp_atk
                    stab = 1.5 if move['type'] in attacker_data['types'] else 1.0
                    mult = type_multiplier(move['type'], defender_data['types'])
                    crit = 1.5 if random.random() < 0.0625 else 1.0
                    # burn halves attack if physical
                    eff_attack = attack_stat * (0.5 if atk_status == Status.BURN and move['damage_class']=='physical' else 1.0)
                    modifier = stab * mult * crit
                    dmg = calc_damage(L, power, eff_attack, defense_stat, modifier)
                    def_curr = max(0, def_curr - dmg)
                    log.append(f"{user_name} used {move['name']} -> -{dmg} (effectiveness x{mult})")
                else:
                    log.append(f"{user_name} used {move['name']} (no direct damage in this sim)")
                # attempt to apply status (if move has effect text & chance)
                new_status = await apply_status_chance(move, def_status)
                if new_status and new_status != def_status:
                    def_status = new_status
                    log.append(f"{target_name} is now {def_status}!")
            else:
                user_name = defender_data['name']
                target_name = attacker_data['name']
                move = def_move
                user_status = def_status
                target_status = atk_status
                if user_status == Status.PARALYSIS and random.random() < 0.25:
                    log.append(f"{user_name} is paralyzed and can't move!")
                    continue
                if not hits(move.get('accuracy')):
                    log.append(f"{user_name} used {move['name']} but it missed!")
                    continue
                power = move.get('power') or 0
                if power > 0:
                    attack_stat = def_attack if move['damage_class']=='physical' else def_sp_atk
                    defense_stat = atk_attack if move['damage_class']=='physical' else atk_sp_atk
                    stab = 1.5 if move['type'] in defender_data['types'] else 1.0
                    mult = type_multiplier(move['type'], attacker_data['types'])
                    crit = 1.5 if random.random() < 0.0625 else 1.0
                    eff_attack = attack_stat * (0.5 if def_status == Status.BURN and move['damage_class']=='physical' else 1.0)
                    modifier = stab * mult * crit
                    dmg = calc_damage(L, power, eff_attack, defense_stat, modifier)
                    atk_curr = max(0, atk_curr - dmg)
                    log.append(f"{user_name} used {move['name']} -> -{dmg} (effectiveness x{mult})")
                else:
                    log.append(f"{user_name} used {move['name']} (no direct damage in this sim)")
                new_status = await apply_status_chance(move, atk_status)
                if new_status and new_status != atk_status:
                    atk_status = new_status
                    log.append(f"{target_name} is now {atk_status}!")

            # check faint
            if atk_curr <= 0 or def_curr <= 0:
                break

        # end-of-turn status damage
        def apply_eot(name, status, curr_hp, max_hp):
            nonlocal atk_curr, def_curr
            if status == Status.BURN:
                dmg = max(1, int(max_hp / 16))
                curr_hp = max(0, curr_hp - dmg)
                log.append(f"{name} is hurt by its burn for {dmg} HP.")
            elif status == Status.POISON:
                dmg = max(1, int(max_hp / 8))
                curr_hp = max(0, curr_hp - dmg)
                log.append(f"{name} is hurt by poison for {dmg} HP.")
            return curr_hp

        atk_curr = apply_eot(attacker_data['name'], atk_status, atk_curr, atk_hp)
        def_curr = apply_eot(defender_data['name'], def_status, def_curr, def_hp)

        # break if someone fainted
        if atk_curr <= 0 or def_curr <= 0:
            break

    # determine winner
    winner = None
    if atk_curr > 0 and def_curr <= 0:
        winner = attacker_data['name']
    elif def_curr > 0 and atk_curr <= 0:
        winner = defender_data['name']
    else:
        winner = None  # draw

    return {"winner": winner, "turns": turn, "log": log}
