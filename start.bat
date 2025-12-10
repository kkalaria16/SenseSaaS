@echo off

echo Starting SQL Agent Chat Application (Segregated Structure)...
echo.

:: Backend Setup
echo [1/4] Setting up Backend...
if not exist "backend\.venv\" (
    echo Creating virtual environment in backend...
    cd backend
    uv init
    uv venv
    call .venv\Scripts\activate.bat
    uv add -r requirements.txt
    cd ..
)

:: Frontend Setup
echo [2/4] Setting up Frontend...
if exist "frontend\package.json" (
    cd frontend
    if not exist "node_modules\" (
        echo Installing frontend dependencies...
        call npm install
    )
    cd ..
)

echo.
echo [3/4] Starting FastAPI Backend...
:: We run from backend dir so app.py finds local description files easily
start "Backend" cmd /k "cd backend && call .venv\Scripts\activate.bat && uvicorn app:app --reload --host 0.0.0.0 --port 8000"

echo [4/4] Starting Frontend (if applicable)...
:: If there's a dev server (like Vite/Next), run it. If it's just static + templates served by FastAPI, we might strictly need npm run build or watch.
:: The previous start.bat had "npm run dev".
if exist "frontend\package.json" (
    start "Frontend" cmd /k "cd frontend && npm run dev"
)

echo.
echo Services starting...
echo - Backend/App: http://localhost:8000
echo.
timeout /t 5 > nul
start http://localhost:8000

echo To stop, close the terminal windows.