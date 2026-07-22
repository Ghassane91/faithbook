# ============================================================================
#  Arrête proprement les conteneurs FaithBook (les données sont conservées).
#  Compilé en FaithBook-Stop.exe. À garder dans le dossier du projet.
# ============================================================================
Add-Type -AssemblyName System.Windows.Forms

if ($PSScriptRoot) {
    $root = $PSScriptRoot
} else {
    $root = Split-Path -Parent ([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)
}

if (-not (Test-Path (Join-Path $root 'docker-compose.yml'))) {
    [System.Windows.Forms.MessageBox]::Show(
        "docker-compose.yml introuvable dans :`n$root", 'FaithBook',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    exit 1
}
Set-Location $root

$proc = Start-Process -FilePath 'docker' -ArgumentList 'compose', 'stop' `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru -Wait

if ($env:FAITHBOOK_TEST -eq '1') { exit $proc.ExitCode }

if ($proc.ExitCode -eq 0) {
    [System.Windows.Forms.MessageBox]::Show(
        'FaithBook est arrêté. Vos données et vos captures sont conservées.', 'FaithBook',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
} else {
    [System.Windows.Forms.MessageBox]::Show(
        "L'arrêt a rencontré un problème. Vérifiez Docker Desktop.", 'FaithBook',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
}
