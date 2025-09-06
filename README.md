# Pokémon MCP Server

An **MCP (Model Context Protocol) Server** that provides:
1. **Pokémon Data Resource** – exposes Pokémon stats, types, abilities, moves, and evolution information.  
2. **Battle Simulation Tool** – allows AI models (or users) to simulate battles between any two Pokémon with mechanics like type effectiveness, move damage, turn order, and status effects.

This project bridges AI models with Pokémon knowledge, enabling both querying Pokémon data and running battle simulations.

---

## 📂 Project Structure

**pokemon-mcp-server**/
├── main.py # MCP server entrypoint
├── battle_simulator.py # Battle Simulation Tool
├── requirements.txt # Python dependencies
└── README.md # Documentation

## ⚡ Features

### Pokémon Data Resource
- Provides comprehensive Pokémon data:
  - Base stats (HP, Attack, Defense, Special Attack, Special Defense, Speed)
  - Types (e.g., Fire, Water, Grass)
  - Abilities
  - Available moves & effects
  - Evolution information
- Accessible via MCP resource queries

### Battle Simulation Tool
- Input: any two Pokémon with selected moves
- Core mechanics:
  - ✅ Type effectiveness multipliers (e.g., Water > Fire)  
  - ✅ Damage calculation based on stats and move power  
  - ✅ Turn order determined by Speed  
  - ✅ Status effects: **Paralysis, Burn, Poison**  
- Outputs:
  - Detailed turn-by-turn battle logs
  - Winner declaration
  - JSON result format for easy integration

---

## 🛠️ Installation

Clone this repository:

```bash
git clone https://github.com/AdeetyaDubey5/Pokemon-MCP-Server.git
cd Pokemon-MCP-Server bash
```
Install Dependencies:

```bash
pip install -r requirements.txt
```

Start the server:
```bash
uvicorn main:app --reload
```

## 📊 Example Queries

### 1. Query Pokémon Data

Request: 
```bash
GET /pokemon/pikachu
```

Response:
```bash
{
  "name": "Pikachu",
  "types": ["Electric"],
  "stats": {
    "hp": 35,
    "attack": 55,
    "defense": 40,
    "special-attack": 50,
    "special-defense": 50,
    "speed": 90
  },
  "abilities": [
    {"name": "Static", "is_hidden": false},
    {"name": "Lightning Rod", "is_hidden": true}
  ],
  "moves": ["Thunderbolt", "Quick Attack", "Iron Tail"],
  "evolution_chain": ["Pichu", "Pikachu", "Raichu"]
}
```


