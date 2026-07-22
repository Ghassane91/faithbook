# ============================================================================
#  Synchronise les captures WEB (dossier local OUTPUT_DIR) vers Google Drive.
#  Le conteneur Docker ne peut pas écrire sur le lecteur Google Drive (système
#  de fichiers virtuel « Stream ») ; robocopy natif, lui, le peut. Lancé toutes
#  les 15 min par le Planificateur de tâches. Compilé en sync-drive-web.exe.
# ============================================================================
if ($PSScriptRoot) {
    $base = $PSScriptRoot
} else {
    $base = Split-Path -Parent ([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)
}

# Dossier des captures web = <racine projet>\captures (le dossier parent de capture-bureau\).
$projet = Split-Path -Parent $base
$source = Join-Path $projet 'captures'

# Destination Drive (configurable via sync-drive.config.txt, sinon défaut).
$cfg = Join-Path $base 'sync-drive.config.txt'
$dest = 'G:\Mon Drive\FaithBook\web'
if (Test-Path $cfg) {
    $c = (Get-Content $cfg -Raw -Encoding UTF8).Trim()
    if (-not [string]::IsNullOrWhiteSpace($c)) { $dest = $c }
}

if (-not (Test-Path $source)) { exit 0 }   # rien à synchroniser encore
New-Item -ItemType Directory -Force -Path $dest | Out-Null

$log = Join-Path $base 'sync-drive.log'
# /E sous-dossiers (dossiers datés), /XO ignore les fichiers déjà à jour,
# /R:1 /W:1 réessais minimes, /NP pas de pourcentage, journal compact.
robocopy $source $dest /E /XO /R:1 /W:1 /NP /NFL /NDL /NJH /LOG+:$log 2>&1 | Out-Null
# robocopy : codes 0-7 = succès (8+ = erreur).
if ($LASTEXITCODE -ge 8) {
    Add-Content -Path $log -Value ("{0}  ERREUR robocopy code {1}" -f (Get-Date -Format 's'), $LASTEXITCODE) -Encoding UTF8
    exit 1
}
exit 0
