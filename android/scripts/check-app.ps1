$ErrorActionPreference = 'Stop'
$AndroidRoot = Split-Path -Parent $PSScriptRoot
if (-not $env:JAVA_HOME) {
    $LocalJdk = Join-Path $env:LOCALAPPDATA 'DaftarAndroidTools\jdk21\jdk-21.0.13+9'
    if (Test-Path -LiteralPath (Join-Path $LocalJdk 'bin\java.exe')) { $env:JAVA_HOME = $LocalJdk }
    else { throw 'Set JAVA_HOME to a JDK 21 installation before running Android checks.' }
}
Push-Location -LiteralPath $AndroidRoot
try {
    & .\gradlew.bat --no-daemon :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
    if ($LASTEXITCODE -ne 0) { throw 'Android checks failed. Inspect app/build/reports/tests and lint reports.' }
    $Screenshots = Join-Path $AndroidRoot 'app\build\reports\app-journeys'
    if (-not (Get-ChildItem -LiteralPath $Screenshots -Filter '*.png' -ErrorAction SilentlyContinue)) { throw 'No native journey screenshots were generated.' }
    Write-Output ('Native screenshot review: ' + $Screenshots)
    Write-Output 'Real Google account chooser, Tailscale transport and biometrics still require device acceptance.'
} finally { Pop-Location }
