import asyncio
import json
import random
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, List

router = APIRouter()

# --- GAME STATE ENGINE ---
# Structure: { room_code: { "players": [...], "roles": {...}, "alive": {...}, "votes": {...}, "night_actions": {...} } }
GAME_ROOMS: Dict[str, dict] = {}

class ConnectionManager:
    def __init__(self):
        # Active connections: { room_code: { player_name: WebSocket } }
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room_code: str, player_name: str):
        await websocket.accept()
        if room_code not in self.active_connections:
            self.active_connections[room_code] = {}
            GAME_ROOMS[room_code] = {
                "players": [],
                "roles": {},
                "alive": {},
                "votes": {},
                "night_actions": {},
                "profiles": {},
                "phase": "LOBBY",
                "host": player_name
            }
        
        self.active_connections[room_code][player_name] = websocket
        if player_name not in GAME_ROOMS[room_code]["players"]:
            GAME_ROOMS[room_code]["players"].append(player_name)
        GAME_ROOMS[room_code]["alive"][player_name] = True

    def disconnect(self, room_code: str, player_name: str):
        if room_code in self.active_connections:
            if player_name in self.active_connections[room_code]:
                del self.active_connections[room_code][player_name]
            
            # Clean up the player lists if the game is still in LOBBY phase
            state = GAME_ROOMS.get(room_code)
            if state and state.get("phase") == "LOBBY":
                if player_name in state["players"]:
                    state["players"].remove(player_name)
                if state.get("host") == player_name:
                    state["host"] = state["players"][0] if state["players"] else None
                if player_name in state["alive"]:
                    del state["alive"][player_name]
                if player_name in state["profiles"]:
                    del state["profiles"][player_name]

            if not self.active_connections[room_code]:
                del self.active_connections[room_code]
                if room_code in GAME_ROOMS:
                    del GAME_ROOMS[room_code]

    async def send_personal_message(self, message: dict, room_code: str, player_name: str):
        if room_code in self.active_connections and player_name in self.active_connections[room_code]:
            try:
                await self.active_connections[room_code][player_name].send_text(json.dumps(message))
            except Exception:
                pass

    async def broadcast_to_room(self, message: dict, room_code: str):
        if room_code in self.active_connections:
            payload = json.dumps(message)
            tasks = [
                ws.send_text(payload) 
                for ws in self.active_connections[room_code].values()
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

manager = ConnectionManager()

def check_victory_conditions(room_code: str) -> str:
    """Evaluates the living population to see if a side has won."""
    state = GAME_ROOMS.get(room_code)
    if not state:
        return None
        
    mafia_count = 0
    town_count = 0
    
    for player in state["players"]:
        if state["alive"].get(player, False):
            if state["roles"].get(player) == "MAFIA":
                mafia_count += 1
            else:
                town_count += 1

    if mafia_count == 0:
        return "TOWN"
    if mafia_count >= town_count:
        return "MAFIA"
    return None

@router.websocket("/ws/{room_code}/{player_name}")
async def websocket_endpoint(websocket: WebSocket, room_code: str, player_name: str):
    await manager.connect(websocket, room_code, player_name)
    
    # Sync room status with the newly joined player
    state = GAME_ROOMS[room_code]
    await manager.broadcast_to_room({
        "event": "room_sync",
        "players": state["players"],
        "profiles": state["profiles"],
        "host": state.get("host")
    }, room_code)
    
    await manager.broadcast_to_room({
        "event": "player_joined",
        "player_name": player_name,
        "message": f"{player_name} has entered the nightmare."
    }, room_code)

    try:
        while True:
            data = await websocket.receive_text()
            packet = json.loads(data)
            action = packet.get("action")

            # 1. PROFILE PHOTO SYNC
            if action == "update_profile":
                state["profiles"][player_name] = packet.get("avatar")
                await manager.broadcast_to_room({
                    "event": "profile_updated",
                    "player_name": player_name,
                    "avatar": packet.get("avatar")
                }, room_code)

            # 2. GUARANTEED CARD DEALER
            elif action == "start_game":
                if state.get("host") != player_name:
                    continue
                state["phase"] = "NIGHT"
                state["night_actions"].clear()
                state["votes"].clear()
                for p in state["players"]:
                    state["alive"][p] = True
                players = state["players"]
                
                if len(players) < 4:
                    # Low player count setup: Always guarantee exactly 1 Mafia
                    roles_to_assign = ["MAFIA"]
                    pool = ["DOCTOR", "COP", "STUDENT"]
                    while len(roles_to_assign) < len(players):
                        roles_to_assign.append(random.choice(pool))
                else:
                    # Standard scaling setup
                    num_mafia = max(1, len(players) // 4)
                    roles_to_assign = ["MAFIA"] * num_mafia
                    if len(players) > 1: roles_to_assign.append("DOCTOR")
                    if len(players) > 2: roles_to_assign.append("COP")
                    while len(roles_to_assign) < len(players):
                        roles_to_assign.append("STUDENT")

                random.shuffle(roles_to_assign)
                
                for idx, p in enumerate(players):
                    role = roles_to_assign[idx]
                    state["roles"][p] = role
                    await manager.send_personal_message({
                        "event": "role_assigned",
                        "role": role
                    }, room_code, p)

                await manager.broadcast_to_room({"event": "game_started"}, room_code)

            # 3. NIGHT ACTION RESOLUTION
            elif action == "night_action":
                if not state["alive"].get(player_name, False):
                    continue
                role = packet.get("role")
                target = packet.get("target")
                state["night_actions"][role] = target
                
                # Cache the recorded video if it's the MAFIA action
                if role == "MAFIA":
                    state["murder_video"] = packet.get("videoBase64")
                
                # If the action is initiated by the COP, immediately reply with alignment result
                if role == "COP":
                    target_role = state["roles"].get(target, "STUDENT")
                    is_mafia = (target_role == "MAFIA")
                    await manager.send_personal_message({
                        "event": "investigation_result",
                        "target": target,
                        "is_mafia": is_mafia,
                        "role": target_role
                    }, room_code, player_name)

            # 4. SUNRISE / MORNING BRIEFING CALCULATION
            elif action == "sunrise":
                if state.get("phase") != "NIGHT":
                    continue
                state["phase"] = "DAY"
                winner = check_victory_conditions(room_code)
                if winner:
                    await manager.broadcast_to_room({"event": "game_over", "winner": winner}, room_code)
                    continue

                mafia_target = state["night_actions"].get("MAFIA")
                doctor_target = state["night_actions"].get("DOCTOR")
                
                victim = None
                murder_video = None
                doctor_saved = False
                
                if mafia_target:
                    if doctor_target and mafia_target == doctor_target:
                        doctor_saved = True
                    else:
                        victim = mafia_target
                        murder_video = state.get("murder_video")
                        state["alive"][victim] = False

                # Clear entries for next round
                state["night_actions"].clear()
                state["votes"].clear()
                if "murder_video" in state:
                    del state["murder_video"]

                await manager.broadcast_to_room({
                    "event": "morning_briefing",
                    "victim": victim,
                    "videoBase64": murder_video,
                    "doctorSaved": doctor_saved
                }, room_code)

                # Check if the night murder ended the match
                winner = check_victory_conditions(room_code)
                if winner:
                    await asyncio.sleep(1) # Small buffer to let morning briefing land
                    await manager.broadcast_to_room({"event": "game_over", "winner": winner}, room_code)

            # 5. DAY VOTING SYSTEM
            elif action == "day_action":
                if not state["alive"].get(player_name, False):
                    continue
                voter = packet.get("voter")
                target = packet.get("target")
                state["votes"][voter] = target

            # 6. DUSK / LYNCHING CALCULATION
            elif action == "dusk":
                if state.get("phase") != "DAY":
                    continue
                state["phase"] = "NIGHT"
                winner = check_victory_conditions(room_code)
                if winner:
                    await manager.broadcast_to_room({"event": "game_over", "winner": winner}, room_code)
                    continue

                vote_counts = {}
                for tgt in state["votes"].values():
                    vote_counts[tgt] = vote_counts.get(tgt, 0) + 1

                executed = None
                if vote_counts:
                    max_votes = max(vote_counts.values())
                    highest_voted = [k for k, v in vote_counts.items() if v == max_votes]
                    # Only execute if there isn't an absolute tie
                    if len(highest_voted) == 1:
                        executed = highest_voted[0]
                        state["alive"][executed] = False

                state["votes"].clear()

                await manager.broadcast_to_room({
                    "event": "dusk_briefing",
                    "executed": executed,
                    "role": state["roles"].get(executed) if executed else None
                }, room_code)

                # Check if the execution ended the match
                winner = check_victory_conditions(room_code)
                if winner:
                    await asyncio.sleep(1)
                    await manager.broadcast_to_room({"event": "game_over", "winner": winner}, room_code)

    except WebSocketDisconnect:
        manager.disconnect(room_code, player_name)
        state = GAME_ROOMS.get(room_code)
        if state:
            await manager.broadcast_to_room({
                "event": "room_sync",
                "players": state["players"],
                "profiles": state["profiles"],
                "host": state.get("host")
            }, room_code)
        await manager.broadcast_to_room({
            "event": "player_left",
            "player_name": player_name,
            "message": f"{player_name} vanished into the mist."
        }, room_code)