
@echo off
cd /d "C:\Users\chris\Youtube AI\ai-video"
"C:\Users\chris\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe" "C:\Users\chris\Youtube AI\ai-video\scripts\run_weekly_due.py" --retry-failed --morning-batch --limit 3 >> "C:\Users\chris\Youtube AI\ai-video\data\logs\weekly-7am.log" 2>&1
