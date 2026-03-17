@echo off
title AITeachMe Dev

echo [后端] 启动 FastAPI (http://localhost:8000)...
start "Backend" cmd /k "cd backend && ..\.venv\Scripts\activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

echo [前端] 启动 Vite (http://localhost:5173)...
start "Frontend" cmd /k "cd frontend && npm run dev"

echo 服务已启动，关闭对应窗口即可停止服务
