@echo off
echo 좋은문화병원 근로계약서 자동화 시스템 시작 중...
cd /d "%~dp0"

:: 관리자 앱 (포트 8501)
start "관리자 앱" cmd /k "python -m streamlit run app.py --server.port 8501"

:: 잠시 대기 후 서명 앱 (포트 8502)
timeout /t 2 /nobreak >nul
start "서명 앱" cmd /k "python -m streamlit run sign_app.py --server.port 8502 --server.headless true"

timeout /t 4 /nobreak >nul
start "" "http://localhost:8501"

echo.
echo ✅ 시스템이 시작되었습니다.
echo    관리자 앱 : http://localhost:8501
echo    서명 앱   : http://localhost:8502
echo.
