param([Parameter(ValueFromRemainingArguments = $true)][string[]]$BsgArguments)
$taskPythonCandidates = @()
if ($env:IDF_PYTHON_ENV_PATH) {
    $taskPythonCandidates += Join-Path $env:IDF_PYTHON_ENV_PATH 'Scripts/python.exe'
}
$taskPythonCandidates += Join-Path $env:USERPROFILE '.espressif/python_env/idf5.5_py3.11_env/Scripts/python.exe'
$taskPythonCandidates += Join-Path $env:USERPROFILE '.platformio/penv/Scripts/python.exe'
$taskPython = $taskPythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $taskPython) {
    $taskPythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($taskPythonCommand -and $taskPythonCommand.Source -notmatch 'WindowsApps') {
        $taskPython = $taskPythonCommand.Source
    }
}
if (-not $taskPython) {
    Write-Error 'Python non trovato. Seguire GUIDA_FLASH.md per installare gli strumenti.'
    exit 1
}
& $taskPython (Join-Path $PSScriptRoot 'bsg.py') @BsgArguments
exit $LASTEXITCODE
