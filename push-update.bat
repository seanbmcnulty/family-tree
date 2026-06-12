@echo off
cd /d "%~dp0"
git add -A
git commit -m "Family tree update %date% %time%"
git pull origin main --allow-unrelated-histories -X ours --no-edit
git push -u origin main
echo.
echo Done - https://seanbmcnulty.github.io/family-tree/ redeploys in about a minute.
pause
