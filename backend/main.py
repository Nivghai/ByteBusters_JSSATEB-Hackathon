from fastapi import FastAPI, WebSocket, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import jwt
from passlib.context import CryptContext
from jwt.exceptions import PyJWTError
import random
import asyncio

SECRET_KEY = "your-secret-key-here"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class User(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None
    disabled: Optional[bool] = None

class UserInDB(User):
    hashed_password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class GameCreate(BaseModel):
    game_type: str = "math_fruit"
    max_players: int = Field(default=1, ge=1, le=4)
    difficulty: str = Field(default="elementary", pattern="^(elementary|highschool|college|coding)$")

class GameState:
    def __init__(self):
        self.active_games: Dict = {}
        self.player_scores: Dict = {}
        self.game_history: List = []

game_state = GameState()

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def get_user(username: str) -> Optional[UserInDB]:
    fake_users_db = {
        "student1": {
            "username": "student1",
            "email": "student1@example.com",
            "full_name": "Student One",
            "hashed_password": get_password_hash("math123"),
            "disabled": False,
        }
    }
    return UserInDB(**fake_users_db.get(username)) if username in fake_users_db else None

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except PyJWTError:
        raise credentials_exception
    user = get_user(username=token_data.username)
    if user is None:
        raise credentials_exception
    return user

@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = get_user(form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.websocket("/ws/game/{game_id}/{player_id}")
async def game_websocket(websocket: WebSocket, game_id: str, player_id: str):
    await websocket.accept()
    try:
        if game_id not in game_state.active_games:
            await websocket.send_json({"error": "Game not found"})
            await websocket.close()
            return
        game = game_state.active_games[game_id]
        if player_id not in game["players"]:
            await websocket.send_json({"error": "Player not in game"})
            await websocket.close()
            return
        
        def reset_game_state():
            difficulty = game["difficulty"]
            if difficulty == "elementary":
                a, b = random.randint(1, 5), random.randint(1, 5)
                game["current_problem"] = f"{a} + {b}"
                correct_answer = a + b
                options = [correct_answer, correct_answer + random.randint(1, 3), correct_answer - random.randint(1, 3)]
            elif difficulty == "highschool":
                a, b, c = random.randint(1, 5), random.randint(1, 5), random.randint(1, 5)
                game["current_problem"] = f"Solve: {a}x² + {b}x - {c} = 0 (one root)"
                disc = b**2 - 4*a*c
                correct_answer = round((-b + disc**0.5) / (2*a), 2) if disc >= 0 else 0
                options = [
                    correct_answer,
                    round(correct_answer + random.uniform(1, 2), 2),
                    round(correct_answer - random.uniform(1, 2), 2)
                ]
            elif difficulty == "college":
                a, b = random.randint(1, 5), random.randint(1, 5)
                game["current_problem"] = f"Integrate: ∫ {a}x^{b} dx"
                correct_answer = f"{a/(b+1)}x^{b+1}"
                options = [correct_answer, f"{a}x^{b}", f"{a}x^{b+1}"]
            else:  # coding
                problems = [
                    ("What’s Python’s output? print(2 + 3)", "5", ["5", "23", "6"]),
                    ("What’s JavaScript’s typeof null?", "object", ["object", "null", "undefined"]),
                    ("What’s Python’s len([1, 2, 3])?", "3", ["3", "2", "4"]),
                    ("What’s JavaScript’s 2 + '2'?", "22", ["22", "4", "2"]),
                    ("In Python, what’s type(3.14)?", "float", ["float", "int", "str"]),
                    ("What’s JavaScript’s [] instanceof Array?", "true", ["true", "false", "undefined"]),
                    ("In Python, what’s 5 // 2?", "2", ["2", "2.5", "3"]),
                    ("What’s JavaScript’s '1' == 1?", "true", ["true", "false", "error"]),
                    ("In Python, what’s 'hello'[1]?", "e", ["e", "h", "l"]),
                    ("What’s JavaScript’s parseInt('10px')?", "10", ["10", "10px", "NaN"])
                ]
                prob, correct_answer, options = random.choice(problems)
                game["current_problem"] = prob
                print(f"Selected coding question: {prob}")
            
            random.shuffle(options)
            game["fruits"] = []
            min_distance = 0.1
            for opt in options:
                max_attempts = 100
                for _ in range(max_attempts):
                    x = random.uniform(0.1, 0.9)
                    y = random.uniform(0.1, 0.9)
                    overlaps = False
                    for existing_fruit in game["fruits"]:
                        dist = ((x - existing_fruit["x"]) ** 2 + (y - existing_fruit["y"]) ** 2) ** 0.5
                        if dist < min_distance:
                            overlaps = True
                            break
                    if not overlaps:
                        game["fruits"].append({"x": x, "y": y, "sliced": False, "value": opt})
                        break
                else:
                    game["fruits"].append({"x": x, "y": y, "sliced": False, "value": opt})
            game["correct_answer"] = correct_answer
            game["status"] = "waiting"
            print(f"Reset: Score = {game_state.player_scores.get(player_id, 0)}, Status = {game['status']}")
        
        if "current_problem" not in game:
            reset_game_state()
        
        await websocket.send_json({
            "problem": game["current_problem"],
            "fruits": game["fruits"],
            "score": game_state.player_scores.get(player_id, 0),
            "status": game["status"],
            "timestamp": datetime.utcnow().isoformat()
        })
        print(f"Initial send: Score = {game_state.player_scores.get(player_id, 0)}, Status = {game['status']}")

        while True:
            try:
                data = await websocket.receive_json()
                if data.get("type") == "slice":
                    sliced_value = data["value"]
                    current_score = game_state.player_scores.get(player_id, 0)
                    print(f"Slice received: Score = {current_score}, Sliced value = {sliced_value}")
                    if sliced_value == game["correct_answer"]:
                        game_state.player_scores[player_id] = current_score + 10
                        game["status"] = "correct"
                        print(f"Correct: New score = {game_state.player_scores[player_id]}, Status = {game['status']}")
                        await websocket.send_json({
                            "problem": game["current_problem"],
                            "fruits": game["fruits"],
                            "score": game_state.player_scores.get(player_id, 0),
                            "status": game["status"],
                            "timestamp": datetime.utcnow().isoformat()
                        })
                        # Removed await asyncio.sleep(1) for instant transition
                        reset_game_state()
                        await websocket.send_json({
                            "problem": game["current_problem"],
                            "fruits": game["fruits"],
                            "score": game_state.player_scores.get(player_id, 0),
                            "status": game["status"],
                            "timestamp": datetime.utcnow().isoformat()
                        })
                        print(f"After reset send: Score = {game_state.player_scores.get(player_id, 0)}, Status = {game['status']}")
                    else:
                        game_state.player_scores[player_id] = max(0, current_score - 5)
                        game["status"] = "wrong"
                        print(f"Wrong: New score = {game_state.player_scores[player_id]}, Status = {game['status']}")
                        for fruit in game["fruits"]:
                            fruit["sliced"] = False
                        await websocket.send_json({
                            "problem": game["current_problem"],
                            "fruits": game["fruits"],
                            "score": game_state.player_scores.get(player_id, 0),
                            "status": game["status"],
                            "timestamp": datetime.utcnow().isoformat()
                        })
            except Exception as e:
                await websocket.send_json({"error": f"Processing error: {str(e)}"})
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        if game_id in game_state.active_games:
            game = game_state.active_games[game_id]
            if player_id in game["players"]:
                game["players"].remove(player_id)
                if not game["players"]:
                    del game_state.active_games[game_id]
        await websocket.close()

@app.post("/games/create", response_model=dict)
async def create_game(game_data: GameCreate, current_user: User = Depends(get_current_user)):
    game_id = f"game_{len(game_state.active_games)}"
    game_state.active_games[game_id] = {
        "type": game_data.game_type,
        "status": "waiting",
        "players": [current_user.username],
        "max_players": game_data.max_players,
        "difficulty": game_data.difficulty,
        "created_by": current_user.username,
        "created_at": datetime.utcnow().isoformat(),
        "fruits": []
    }
    game_state.player_scores[current_user.username] = 0
    return {"game_id": game_id, "game": game_state.active_games[game_id]}

@app.get("/games/active")
async def get_active_games(current_user: User = Depends(get_current_user)):
    return {"games": game_state.active_games, "total_games": len(game_state.active_games)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)