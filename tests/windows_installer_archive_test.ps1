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
$env:JAMBOREE_SKIP_CODE_BACKUP = '1'
$env:JAMBOREE_NO_PAUSE = '1'
$env:JAMBOREE_SOURCE_COMMIT = $CommitSha
$env:JAMBOREE_SOURCE_REF = if ($env:GITHUB_HEAD_REF) { $env:GITHUB_HEAD_REF } else { $env:GITHUB_REF_NAME }

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

    $installedCommit = (Get-Content (Join-Path $install '.jamboree_source_commit') -Raw).Trim()
    if ($installedCommit -ne $CommitSha) {
        throw "Installed fingerprint mismatch: expected $CommitSha, got $installedCommit"
    }

    # Exercise the exact production fallback on a real Windows runner. The fake
    # keyring reproduces ERROR_NO_SUCH_LOGON_SESSION (1312); DPAPI itself is real.
    $env:JAMBOREE_CREDENTIAL_FILE = Join-Path $env:RUNNER_TEMP 'jamboree-dpapi-ci.json'
    $dpapiTest = Join-Path $env:RUNNER_TEMP 'verify_jamboree_dpapi.py'
    @'
from pathlib import Path
import json
import os

from jamboree.core import credentials as credentials_module
from jamboree.core.credentials import CredentialManager

class BrokenWindowsKeyring:
    def set_password(self, *_args, **_kwargs):
        raise OSError(1312, "CredRead", "A specified logon session does not exist")
    def get_password(self, *_args, **_kwargs):
        raise OSError(1312, "CredRead", "A specified logon session does not exist")
    def delete_password(self, *_args, **_kwargs):
        raise OSError(1312, "CredDelete", "A specified logon session does not exist")

credentials_module.keyring = BrokenWindowsKeyring()
alias = "CI-DPAPI"
username = "ci-issued-user"
password = "ci-issued-secret"
assert CredentialManager.store_credentials(alias, username, password)
assert CredentialManager.get_credentials(alias) == (username, password)
status = CredentialManager.status(alias)
assert status["stored"] is True
assert status["secure"] is True
assert status["backend"] == "windows-dpapi-machine"
raw = Path(os.environ["JAMBOREE_CREDENTIAL_FILE"]).read_text(encoding="utf-8")
assert username not in raw
assert password not in raw
doc = json.loads(raw)
assert doc["records"][alias]["scope"] == "machine"
print("Native Windows machine-DPAPI fallback smoke test passed:", status["backend"])
'@ | Set-Content -Path $dpapiTest -Encoding UTF8

    $oldPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = $install
    try {
        & $python $dpapiTest
        if ($LASTEXITCODE -ne 0) {
            throw "Native Windows DPAPI fallback test failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        $env:PYTHONPATH = $oldPythonPath
    }

    # Prove that executing install_jamboreeLite.cmd from the live installation
    # actually updates from a clean requested ref instead of silently no-oping.
    $updateRef = if ($env:GITHUB_HEAD_REF) { $env:GITHUB_HEAD_REF } else { $env:GITHUB_REF_NAME }
    if (-not $updateRef) {
        throw 'Could not resolve a Git ref for the in-place updater test.'
    }
    $env:JAMBOREE_REF = $updateRef
    $env:JAMBOREE_SOURCE_COMMIT = $null
    $env:JAMBOREE_SOURCE_REF = $null

    $basePath = Join-Path $install 'base.txt'
    $sentinel = '{"stbs":{"INSTALLER-SENTINEL":{"stb":"R0000000000-00"}}}'
    Set-Content -Path $basePath -Value $sentinel -Encoding UTF8
    $appPath = Join-Path $install 'jamboree\app.py'
    Add-Content -Path $appPath -Value '# STALE_LOCAL_MARKER'

    Write-Host "Running installed-tree updater via ref: $updateRef"
    & cmd.exe /d /c "call `"$(Join-Path $install 'install_jamboreeLite.cmd')`""
    if ($LASTEXITCODE -ne 0) {
        throw "Installed-tree update failed with exit code $LASTEXITCODE."
    }

    $updatedCommit = (Get-Content (Join-Path $install '.jamboree_source_commit') -Raw).Trim()
    if ($updatedCommit -ne $CommitSha) {
        throw "Updater fingerprint mismatch: expected $CommitSha, got $updatedCommit"
    }
    if ((Get-Content $appPath -Raw) -match 'STALE_LOCAL_MARKER') {
        throw 'Updater did not replace stale runtime source.'
    }
    if ((Get-Content $basePath -Raw).Trim() -ne $sentinel) {
        throw 'Updater did not preserve base.txt.'
    }
    & $python -c "import jamboree.app; print('Installed-tree updater smoke test passed')"
    if ($LASTEXITCODE -ne 0) {
        throw "Updated application import failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
