# main.py
from fastapi import FastAPI
from pokemon_data import router as pokemon_router
from battle_simulator import router as battle_router

app = FastAPI(title="MCP Pokémon Server")

# include routers
app.include_router(pokemon_router, prefix="/pokemon", tags=["Pokemon Data"])
app.include_router(battle_router, prefix="/battle", tags=["Battle Simulation"])

# discovery endpoint for LLMs / MCP pattern
@app.get("/.well-known/mcp-resources")
async def list_resources():
    return {
        "resources": [
            {"name": "pokemon-data", "endpoint": "/pokemon/{name_or_id}", "methods": ["GET"]},
            {"name": "move-data", "endpoint": "/pokemon/move/{name_or_id}", "methods": ["GET"]},
            {"name": "battle-sim", "endpoint": "/battle/simulate", "methods": ["POST"]},
        ],
        "description": "Pokémon data resource + advanced battle simulation tool for LLMs."
    }
