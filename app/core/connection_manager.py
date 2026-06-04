from typing import Dict
from fastapi.websockets import WebSocket

class ConnectionManager:
    def __init__(self):
        # Maps a room_code to a dictionary of {player_name: websocket}
        self.rooms: Dict[str, Dict[str, WebSocket]] = {}
        
        # NEW: Tracks the secret night actions for each room
        self.game_states: Dict[str, dict] = {} 

    async def connect(self, websocket: WebSocket, room_code: str, player_name: str):
        await websocket.accept()
        if room_code not in self.rooms:
            self.rooms[room_code] = {}
        self.rooms[room_code][player_name] = websocket

    def disconnect(self, room_code: str, player_name: str):
        if room_code in self.rooms and player_name in self.rooms[room_code]:
            del self.rooms[room_code][player_name]
            # Clean up the room and game state if everyone leaves
            if not self.rooms[room_code]:
                del self.rooms[room_code]
                if room_code in self.game_states:
                    del self.game_states[room_code]

    async def broadcast(self, message: dict, room_code: str):
        """Sends a JSON message to EVERYONE in the room."""
        if room_code in self.rooms:
            for connection in self.rooms[room_code].values():
                await connection.send_json(message)

    async def send_personal_message(self, message: dict, room_code: str, player_name: str):
        """Sends a JSON message secretly to ONE specific player."""
        if room_code in self.rooms and player_name in self.rooms[room_code]:
            await self.rooms[room_code][player_name].send_json(message)

manager = ConnectionManager()