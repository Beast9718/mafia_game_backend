import asyncio
import json
import random
import os
import httpx
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
        if player_name not in GAME_ROOMS[room_code]["alive"]:
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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

async def verify_ritual_video(video_base64: str, target: str, kill_phrase: str) -> tuple[bool, str]:
    if not GEMINI_API_KEY:
        print("WARNING: GEMINI_API_KEY is not set. Automatically passing verification in development mode.")
        return True, "Dev Mode Bypass: Verification passed (No API Key set)."
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    headers = {"Content-Type": "application/json"}
    
    prompt = (
        f"You are the game arbitrator for a creepy Mafia game. The video shows a mafia player recording their kill ritual.\n"
        f"The player was required to perform the following two actions:\n"
        f"1. Write the exact phrase: \"{kill_phrase}\" on a piece of paper and show it to the camera.\n"
        f"2. Speak the exact phrase: \"{kill_phrase}\" out loud.\n\n"
        f"The target player's name is \"{target}\", which is part of the phrase.\n\n"
        f"Determine if the player successfully and correctly executed both the writing and speaking elements without mistakes.\n"
        f"You MUST return a JSON object with two fields:\n"
        f"- \"verified\": boolean (true if both written and spoken phrases are correct and match the required phrase, false if they made any mistakes, omitted writing/speaking, or targeted the wrong person)\n"
        f"- \"feedback\": a brief description explaining why they succeeded or failed (e.g. \"Perfect execution\", \"Spoke the wrong name: Bob instead of Alice\", \"Did not write anything on paper\", etc.)"
    )
    
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "video/mp4",
                            "data": video_base64
                        }
                    },
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                print(f"Gemini API returned error code {response.status_code}: {response.text}")
                return True, f"Error calling Gemini ({response.status_code}). Defaulting to success."
            
            result = response.json()
            # Parse the content
            text_response = result['candidates'][0]['content']['parts'][0]['text']
            data = json.loads(text_response)
            verified = bool(data.get("verified", False))
            feedback = str(data.get("feedback", "No feedback provided."))
            return verified, feedback
            
    except Exception as e:
        print(f"Failed to verify video using Gemini: {e}")
        return True, f"Verification failed to run: {str(e)}. Defaulting to success."

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

async def broadcast_room_sync(room_code: str):
    state = GAME_ROOMS.get(room_code)
    if not state:
        return
    dead_roles = {
        p: state["roles"].get(p, "STUDENT")
        for p, is_alive in state["alive"].items()
        if not is_alive
    }
    await manager.broadcast_to_room({
        "event": "room_sync",
        "players": state["players"],
        "profiles": state["profiles"],
        "host": state.get("host"),
        "phase": state.get("phase", "LOBBY"),
        "alive": state.get("alive", {}),
        "dead_roles": dead_roles
    }, room_code)

@router.websocket("/ws/{room_code}/{player_name}")
async def websocket_endpoint(websocket: WebSocket, room_code: str, player_name: str):
    await manager.connect(websocket, room_code, player_name)
    state = GAME_ROOMS.get(room_code)
    
    # Sync room status with the newly joined player
    await broadcast_room_sync(room_code)
    
    await manager.broadcast_to_room({
        "event": "player_joined",
        "player_name": player_name,
        "message": f"{player_name} has entered the nightmare."
    }, room_code)

    # If the game has already started, resend the player's role to them!
    if state and state.get("phase") in ["DAY", "NIGHT"]:
        role = state["roles"].get(player_name)
        if role:
            await manager.send_personal_message({
                "event": "role_assigned",
                "role": role
            }, room_code, player_name)

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
                
                # Cache the recorded video and ritual details if it's the MAFIA action
                if role == "MAFIA":
                    state["murder_video"] = packet.get("videoBase64")
                    state["murder_phrase"] = packet.get("killPhrase")
                
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
                ritual_status = None
                ritual_feedback = None
                
                if mafia_target:
                    murder_video = state.get("murder_video")
                    murder_phrase = state.get("murder_phrase")
                    
                    verified = True
                    feedback = "No ritual video was submitted."
                    
                    if murder_video:
                        verified, feedback = await verify_ritual_video(murder_video, mafia_target, murder_phrase)
                    
                    if verified:
                        ritual_status = "success"
                        ritual_feedback = feedback
                        if doctor_target and mafia_target == doctor_target:
                            doctor_saved = True
                        else:
                            victim = mafia_target
                            state["alive"][victim] = False
                    else:
                        ritual_status = "failed"
                        ritual_feedback = feedback

                # Clear entries for next round
                state["night_actions"].clear()
                state["votes"].clear()
                if "murder_video" in state:
                    del state["murder_video"]
                if "murder_phrase" in state:
                    del state["murder_phrase"]

                await manager.broadcast_to_room({
                    "event": "morning_briefing",
                    "victim": victim,
                    "videoBase64": murder_video,
                    "doctorSaved": doctor_saved,
                    "ritual_status": ritual_status,
                    "ritual_feedback": ritual_feedback,
                    "attempted_target": mafia_target
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

                # Check for failure to vote system execution penalty
                failed_to_vote = []
                for p in state["players"]:
                    if state["alive"].get(p, False) and p not in state["votes"]:
                        failed_to_vote.append(p)
                        state["alive"][p] = False

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
                        if executed not in failed_to_vote:
                            state["alive"][executed] = False

                state["votes"].clear()

                await manager.broadcast_to_room({
                    "event": "dusk_briefing",
                    "executed": executed,
                    "failed_to_vote": failed_to_vote
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
            await broadcast_room_sync(room_code)
        await manager.broadcast_to_room({
            "event": "player_left",
            "player_name": player_name,
            "message": f"{player_name} vanished into the mist."
        }, room_code)