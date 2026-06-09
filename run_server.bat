@echo off
cd /d "F:\co work dashboard"
echo ============================================================
echo  Starting Dashboard Web Server on Port 48081
echo  Accessible at: http://agent-ab-sandbox.tjinternal.com:48081/
echo ============================================================
py -m http.server 48081 --bind 0.0.0.0
pause
