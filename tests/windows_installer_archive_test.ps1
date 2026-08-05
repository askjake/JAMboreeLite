param(
    [Parameter(Mandatory = $true)]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [string]$CommitSha
)

$ErrorActionPreference = 'Stop'
$archive = Join-Path $env:RUNNER_TEMP 'JAMboreeLite-source.zip'
$extract = Join-Path $env:RUNNER_TEMP 'JAMboreeLite-source'
$install = Join-Path $env:RUNNER_TEMP 'JAMboreeLite-installed'
$url = "https://github.com/$Repository/archive/$CommitSha.zip"

Write-Host "Downloading exact repository archive: $url"
Invoke-WebRequest -Uri $url -OutFile $archive

if (Test-Path $extract) {
    Remove-Item $extract -Recurse -Force
}
Expand-Archive -Path $archive -DestinationPath $extract -Force

$installer = Get-ChildItem -Path $extract -Filter install_jamboreeLite.cmd -Recurse | Select-Object -First 1
if (-not $installer) {
    throw 'install_jamboreeLite.cmd was not found in the downloaded archive.'
}

$env:JAMBOREE_INSTALL_DIR = $install
$env:JAMBOREE_SKIP_SHORTCUTS = '1'
$env:JAMBOREE_SKIP_STARTUP = '1'
$env:JAMBOREE_NO_PAUSE = '1'

Write-Host "Running archived installer: $($installer.FullName)"
& cmd.exe /d /c "call `"$($installer.FullName)`""
if ($LASTEXITCODE -ne 0) {
    throw "Archived installer failed with exit code $LASTEXITCODE."
}

$python = Join-Path $install 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw "Installed virtual-environment Python was not created: $python"
}

Push-Location $install
try {
    & $python -c "import jamboree.app; print('Archived Windows installer smoke test passed')"
    if ($LASTEXITCODE -ne 0) {
        throw "Installed application import failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
