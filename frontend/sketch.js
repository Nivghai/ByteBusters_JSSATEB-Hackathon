let socket;
let token;
let gameId;
let playerId;
let fruits = [];
let score = 0;
let gameStartTime = null;
let isOnBreak = false;
let breakStartTime = 0;
let lastSliceTime = 0;
let showingFeedback = false;  // Flag to delay new question processing
let pendingData = null;       // Store next question data during feedback

function setup() {
    let canvas = createCanvas(600, 400);
    canvas.parent('canvas');
    textAlign(CENTER, CENTER);
    textSize(14);
}

function draw() {
    if (gameStartTime !== null) {
        let elapsedTime = (millis() - gameStartTime) / 1000;
        if (!isOnBreak && elapsedTime >= 60) {
            startBreak();
        }
    }

    if (isOnBreak) {
        let breakElapsed = (millis() - breakStartTime) / 1000;
        if (breakElapsed >= 60) {
            endBreak();
        }
        displayBreakScreen();
        return;
    }

    background(220);

    for (let fruit of fruits) {
        if (!fruit.sliced) {
            if (!fruit.hasOwnProperty('opacity')) {
                fruit.opacity = 0;
                fruit.fadeStartTime = millis();
            }

            let fadeElapsed = (millis() - fruit.fadeStartTime) / 1000;
            fruit.opacity = constrain(fadeElapsed, 0, 1);

            fill(255, 165, 0, fruit.opacity * 255);
            ellipse(fruit.x * width, fruit.y * height, 50, 50);
            fill(0, fruit.opacity * 255);
            let displayValue = String(fruit.value);
            if (displayValue.length > 6) {
                displayValue = displayValue.substring(0, 6);
            }
            text(displayValue, fruit.x * width, fruit.y * height);
        }
    }
    checkSlice(mouseX, mouseY);
}

function checkSlice(x, y) {
    if (isOnBreak || gameStartTime === null || showingFeedback) return;

    let currentTime = millis();
    if (currentTime - lastSliceTime < 500) return;

    for (let i = 0; i < fruits.length; i++) {
        if (!fruits[i].sliced && fruits[i].opacity >= 1) {
            let d = dist(x, y, fruits[i].x * width, fruits[i].y * height);
            if (d < 25) {
                fruits[i].sliced = true;
                lastSliceTime = currentTime;
                console.log('Slicing fruit with value:', fruits[i].value);
                socket.send(JSON.stringify({ type: 'slice', value: fruits[i].value }));
                return;
            }
        }
    }
}

function startBreak() {
    isOnBreak = true;
    breakStartTime = millis();
    console.log('Break started');
}

function endBreak() {
    isOnBreak = false;
    gameStartTime = millis();
    console.log('Break ended, game resumed');
}

function displayBreakScreen() {
    background(0, 0, 0, 200);
    fill(255);
    textSize(32);
    text("Screen Freeze: Break Time", width / 2, height / 2 - 20);
    textSize(20);
    let breakElapsed = (millis() - breakStartTime) / 1000;
    let timeLeft = Math.max(0, 60 - Math.floor(breakElapsed));
    text(`Break: ${timeLeft}s`, width / 2, height / 2 + 20);
}

async function login() {
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    try {
        const response = await fetch('http://localhost:8000/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `username=${username}&password=${password}`
        });
        const responseText = await response.text();
        if (response.ok) {
            const data = JSON.parse(responseText);
            token = data.access_token;
            playerId = username;
            document.getElementById('login').style.display = 'none';
            document.getElementById('difficulty').style.display = 'block';
        } else {
            alert('Login failed: ' + responseText);
        }
    } catch (error) {
        alert('Login error: ' + error.message);
    }
}

async function startGame(difficulty) {
    try {
        const response = await fetch('http://localhost:8000/games/create', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ difficulty: difficulty })
        });
        const data = await response.json();
        if (response.ok) {
            gameId = data.game_id;
            document.getElementById('difficulty').style.display = 'none';
            document.getElementById('game').style.display = 'block';
            gameStartTime = millis();
            console.log('Game started, timer initiated');
            connectWebSocket();
        } else {
            alert('Failed to create game: ' + JSON.stringify(data));
        }
    } catch (error) {
        alert('Game creation error: ' + error.message);
    }
}

function connectWebSocket() {
    socket = new WebSocket(`ws://localhost:8000/ws/game/${gameId}/${playerId}`);
    socket.onopen = () => {
        console.log('WebSocket connected');
    };
    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('WebSocket message:', data);
        if (data.error) {
            alert(data.error);
            return;
        }

        // If showing feedback, queue the next message
        if (showingFeedback && data.status === 'waiting') {
            pendingData = data;
            return;
        }

        document.getElementById('equation').innerText = data.problem || 'No problem received';
        score = data.score || 0;
        document.getElementById('score-value').innerText = score;

        if (data.status === 'correct') {
            showingFeedback = true;
            document.getElementById('feedback').innerText = "Correct Answer!";
            setTimeout(() => {
                fruits = [];
                document.getElementById('feedback').innerText = "";
                showingFeedback = false;
                // Process any pending new question
                if (pendingData) {
                    processPendingData(pendingData);
                    pendingData = null;
                }
            }, 500);  // Show feedback for 0.5s
        } else if (data.status === 'wrong') {
            document.getElementById('feedback').innerText = "Wrong Answer";
        } else {  // 'waiting' for new question
            document.getElementById('feedback').innerText = "";
            fruits = data.fruits.map(fruit => ({
                ...fruit,
                sliced: false,
                opacity: 0,
                fadeStartTime: millis()
            })) || [];
        }
    };
    socket.onclose = () => {
        console.log('WebSocket closed');
    };
    socket.onerror = (error) => console.error('WebSocket error:', error);
}

function processPendingData(data) {
    document.getElementById('equation').innerText = data.problem || 'No problem received';
    score = data.score || 0;
    document.getElementById('score-value').innerText = score;
    document.getElementById('feedback').innerText = "";
    fruits = data.fruits.map(fruit => ({
        ...fruit,
        sliced: false,
        opacity: 0,
        fadeStartTime: millis()
    })) || [];
}