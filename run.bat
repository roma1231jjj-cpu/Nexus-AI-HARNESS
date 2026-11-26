@echo off
rem Nexus-AI-HARNESS: поднять демон и открыть окно приложения (с проверкой, что демон жив)
setlocal
cd /d %~dp0
set PY=%~dp0.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

rem уже запущен?
powershell -NoProfile -Command "try{(Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8848/api/health).StatusCode|Out-Null; exit 0}catch{exit 1}"
if %errorlevel% neq 0 (
  echo Запускаю демон Nexus...
  start "Nexus-AI-HARNESS daemon" /min "%PY%" run.py 8848
)

rem ждём готовности до 20 секунд
powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 20;$i++){ try{ $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8848/api/health; if($r.StatusCode -eq 200){$ok=$true; break} }catch{}; Start-Sleep -Milliseconds 1000 }; if($ok){exit 0}else{exit 1}"
if %errorlevel% neq 0 (
  echo.
  echo Демон не поднялся за 20 секунд. Последние строки data\daemon.log:
  powershell -NoProfile -Command "if(Test-Path 'data\daemon.log'){Get-Content 'data\daemon.log' -Tail 15}"
  echo.
  pause
  exit /b 1
)

rem интерфейс: отдельное окно, если есть Chrome/Edge, иначе — браузер по умолчанию
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if exist "%CHROME%" (
  start "" "%CHROME%" --app=http://127.0.0.1:8848/ --window-size=1440,940
) else (
  start "" "http://127.0.0.1:8848/"
)
endlocal
