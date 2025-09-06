# pokemon_data.py
import httpx
from cachetools import TTLCache
from typing import Dict, Any
from fastapi import APIRouter, HTTPException

router = APIRouter()
POKEAPI_BASE = "https://pokeapi.co/api/v2"
_cache = TTLCache(maxsize=2000, ttl=60*60)  # 1 hour

async_client = httpx.AsyncClient(timeout=20)

async def fetch_json(url: str) -> Dict[str, Any]:
    if url in _cache:
        return _cache[url]
    r = await async_client.get(url)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Upstream error: {url} ({r.status_code})")
    data = r.json()
    _cache[url] = data
    return data

@router.get("/{name_or_id}")
async def pokemon(name_or_id: str):
    """
    Returns an adapted Pokémon JSON with stats, types, abilities, moves (name+url), sprite, evolution_chain.
    """
    url = f"{POKEAPI_BASE}/pokemon/{name_or_id.lower()}"
    p = await fetch_json(url)
    stats = {s['stat']['name']: s['base_stat'] for s in p['stats']}
    types = [t['type']['name'] for t in p['types']]
    abilities = [{"name": a['ability']['name'], "is_hidden": a['is_hidden']} for a in p['abilities']]
    moves = [{"name": m['move']['name'], "url": m['move']['url']} for m in p['moves']]
    sprite = p['sprites']['front_default']
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
        "height": p['height'],
        "weight": p['weight'],
        "stats": stats,
        "types": types,
        "abilities": abilities,
        "moves": moves,
        "sprite": sprite,
        "evolution_chain": evo_chain,
    }

@router.get("/move/{name_or_id}")
async def move(name_or_id: str):
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
