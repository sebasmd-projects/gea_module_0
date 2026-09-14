@echo off
REM ---------------------------------------------------------------------
REM  GEA - Comprobacion de integridad / Integrity check   (Windows)
REM
REM  Sin nada que instalar: usa PowerShell, que viene con Windows desde la 7.
REM  No hay .exe a proposito: un ejecutable sin firmar copiado de una USB es
REM  exactamente lo que un antivirus debe bloquear, y ensenar a saltarse ese
REM  aviso es peor que no traer verificador.
REM ---------------------------------------------------------------------
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "Write-Host '';" ^
  "Write-Host '  GEA - Comprobacion de integridad' -ForegroundColor Cyan;" ^
  "Write-Host '  ================================';" ^
  "Write-Host '';" ^
  "$ok=0; $bad=0; $missing=0;" ^
  "foreach ($line in Get-Content 'manifiesto.sha256' -Encoding UTF8) {" ^
  "  if ($line -notmatch '^[0-9a-fA-F]{64}  ') { continue }" ^
  "  $expected = $line.Substring(0,64).ToLower();" ^
  "  $name = $line.Substring(66);" ^
  "  if (-not (Test-Path -LiteralPath $name)) {" ^
  "    Write-Host ('  FALTA     ' + $name) -ForegroundColor Red; $missing++; continue }" ^
  "  $actual = (Get-FileHash -LiteralPath $name -Algorithm SHA256).Hash.ToLower();" ^
  "  if ($actual -eq $expected) { Write-Host ('  OK        ' + $name) -ForegroundColor Green; $ok++ }" ^
  "  else { Write-Host ('  ALTERADO  ' + $name) -ForegroundColor Red; $bad++ } };" ^
  "Write-Host '';" ^
  "if ($bad -eq 0 -and $missing -eq 0) {" ^
  "  Write-Host ('  Los ' + $ok + ' archivos coinciden con el manifiesto.') -ForegroundColor Green }" ^
  "else { Write-Host ('  ' + $bad + ' alterado(s), ' + $missing + ' ausente(s). NO use este dossier.') -ForegroundColor Red };" ^
  "Write-Host '';" ^
  "Write-Host '  Esto comprueba que los archivos no han cambiado desde que se';" ^
  "Write-Host '  grabaron. Para comprobar ADEMAS el sello Ed25519 y el anclaje en';" ^
  "Write-Host '  la cadena de bloques, suba el PDF en:';" ^
  "Write-Host '  https://geausa.propensionesabogados.com/verify/aegis/asset/certification/' -ForegroundColor Cyan;" ^
  "Write-Host '';" ^
  "Write-Host '  SUBIR EL DOCUMENTO comprueba su integridad.' -ForegroundColor Yellow;" ^
  "Write-Host '  TECLEAR EL CODIGO PUBLICO no: solo muestra la ficha.' -ForegroundColor Yellow;" ^
  "Write-Host '';" ^
  "if ($bad -ne 0 -or $missing -ne 0) { exit 1 } else { exit 0 }"
REM El resultado tambien en el codigo de salida, no solo en la pantalla: quien
REM llame a esto desde otro guion lee el codigo, y salir con 0 tras escribir
REM «NO use este dossier» le dice lo contrario de lo que pone arriba.
set RESULTADO=%ERRORLEVEL%
echo.
pause
exit /b %RESULTADO%
