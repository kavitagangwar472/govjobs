@echo off
rem Daily job update: pull, fetch, commit, push. Log is saved in run_log.txt
cd /d "%~dp0"
set LOG=run_log.txt
echo ===== %date% %time% ===== >> %LOG%

git pull --rebase --autostash >> %LOG% 2>&1
if errorlevel 1 (
  echo PULL FAILED - see messages above >> %LOG%
  exit /b 1
)

python scripts\fetch_jobs.py >> %LOG% 2>&1
if errorlevel 1 (
  echo FETCH FAILED - jobs.json not changed >> %LOG%
  exit /b 1
)

git add data\jobs.json >> %LOG% 2>&1
git diff --staged --quiet
if errorlevel 1 (
  git commit -m "Update jobs %date%" >> %LOG% 2>&1
  git push >> %LOG% 2>&1
  if errorlevel 1 (
    echo PUSH FAILED - check GitHub sign-in >> %LOG%
    exit /b 1
  )
  echo PUSHED OK >> %LOG%
) else (
  echo No changes to publish >> %LOG%
)
exit /b 0
