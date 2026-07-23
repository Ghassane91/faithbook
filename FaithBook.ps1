# ============================================================================
#  Lanceur FaithBook — démarre Docker + les conteneurs et ouvre le navigateur.
#  Compilé en FaithBook.exe (ps2exe, sans console). Doit rester dans le dossier
#  du projet, à côté de docker-compose.yml.
# ============================================================================
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$AppUrl    = 'http://localhost:3000'
$HealthUrl = 'http://localhost:8020/api/health'

# --- Dossier du projet : là où se trouve l'exe (ou le script en test) --------
if ($PSScriptRoot) {
    $root = $PSScriptRoot
} else {
    $root = Split-Path -Parent ([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)
}

# --- Petite fenêtre de progression (pas de console) --------------------------
$form = New-Object System.Windows.Forms.Form
$form.Text = 'FaithBook'
$form.Size = New-Object System.Drawing.Size(440, 160)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::White

$title = New-Object System.Windows.Forms.Label
$title.Text = 'FaithBook'
$title.Font = New-Object System.Drawing.Font('Segoe UI', 17, [System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(22, 18)
$form.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.Text = 'Démarrage…'
$status.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$status.AutoSize = $false
$status.Size = New-Object System.Drawing.Size(390, 48)
$status.Location = New-Object System.Drawing.Point(24, 60)
$form.Controls.Add($status)

$form.Show()
[System.Windows.Forms.Application]::DoEvents()

function Set-Status([string]$t) {
    $status.Text = $t
    [System.Windows.Forms.Application]::DoEvents()
}

function Fail([string]$t) {
    $form.Hide()
    [System.Windows.Forms.MessageBox]::Show($t, 'FaithBook',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    exit 1
}

function Test-Docker {
    & docker info *> $null 2>&1
    return ($LASTEXITCODE -eq 0)
}

# --- 0. Vérifs de base -------------------------------------------------------
if (-not (Test-Path (Join-Path $root 'docker-compose.yml'))) {
    Fail("docker-compose.yml introuvable dans :`n$root`n`nPlacez FaithBook.exe dans le dossier du projet FaithBook.")
}
Set-Location $root

# --- 1. Docker démarré ? sinon on lance Docker Desktop et on attend ----------
Set-Status 'Vérification de Docker…'
if (-not (Test-Docker)) {
    Set-Status 'Démarrage de Docker Desktop… (cela peut prendre une minute)'
    $dd = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dd) { Start-Process $dd } else {
        Fail('Docker Desktop est introuvable. Installez Docker Desktop, puis relancez FaithBook.')
    }
    $ok = $false
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 2
        [System.Windows.Forms.Application]::DoEvents()
        if (Test-Docker) { $ok = $true; break }
    }
    if (-not $ok) {
        Fail('Docker ne répond pas encore. Ouvrez Docker Desktop, attendez qu''il soit "running", puis relancez FaithBook.')
    }
}

# --- 2. Lancer les conteneurs (fenêtre réactive pendant un build éventuel) ----
Set-Status 'Lancement de FaithBook… (le tout premier démarrage peut prendre 1–2 minutes)'
$proc = Start-Process -FilePath 'docker' -ArgumentList 'compose', 'up', '-d' `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru
while (-not $proc.HasExited) {
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.Application]::DoEvents()
}
if ($proc.ExitCode -ne 0) {
    Fail('Le démarrage des conteneurs a échoué. Ouvrez Docker Desktop et vérifiez son état, puis relancez.')
}

# --- 3. Attendre que l'API réponde ------------------------------------------
Set-Status 'Attente du service web…'
$up = $false
for ($i = 0; $i -lt 90; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $HealthUrl
        if ($r.StatusCode -eq 200) { $up = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
    [System.Windows.Forms.Application]::DoEvents()
}

# --- 4. Ouvrir le navigateur -------------------------------------------------
# Mode test : ne pas ouvrir le navigateur (utilisé pour valider le lanceur).
if ($env:FAITHBOOK_TEST -eq '1') {
    Set-Status ("Test OK — service prêt : {0}" -f $up)
    Start-Sleep -Seconds 1
    $form.Close()
    exit 0
}

Set-Status 'Ouverture de FaithBook dans Chrome…'
$chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($chrome) {
    # --new-window : ouvre FaithBook dans sa propre fenêtre Chrome.
    Start-Process $chrome -ArgumentList '--new-window', $AppUrl
} else {
    Start-Process $AppUrl  # repli : navigateur par défaut
}
Start-Sleep -Milliseconds 1500
$form.Close()
