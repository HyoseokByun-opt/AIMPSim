@echo off
REM  Downloads the local language model of the AI tab (llama-server and a
REM  GGUF model, checked by SHA-256) into AIMPSim\llm\. The offline package
REM  already holds it. Add --list to see the models, --model NAME for another.
call "%~dp0..\_common.bat" || (pause & exit /b 1)
%MPY% "%~dp0get_model.py" %*
pause
