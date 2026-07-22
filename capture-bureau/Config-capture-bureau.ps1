# ============================================================================
#  Configuration de la capture planifiée du bureau.
#  Fenêtre à double-cliquer : choisir l'heure + le dossier de destination,
#  enregistrer la tâche Windows quotidienne, ou tester tout de suite.
#  Compilé en Config-capture-bureau.exe (sans console).
# ============================================================================
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$TaskName = 'FaithBook - Capture bureau'

if ($PSScriptRoot) {
    $base = $PSScriptRoot
} else {
    $base = Split-Path -Parent ([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)
}
$exe = Join-Path $base 'capture-bureau.exe'
$cfg = Join-Path $base 'bureau.config.txt'

# Valeurs par défaut / rechargées
$defaultDir = Join-Path $env:USERPROFILE 'FaithBook-captures\bureau'
$curDir = $defaultDir
if (Test-Path $cfg) {
    $c = (Get-Content $cfg -Raw -Encoding UTF8).Trim()
    if (-not [string]::IsNullOrWhiteSpace($c)) { $curDir = $c }
}

# --- Fenêtre -----------------------------------------------------------------
$form = New-Object System.Windows.Forms.Form
$form.Text = 'FaithBook — capture du bureau'
$form.Size = New-Object System.Drawing.Size(560, 340)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.BackColor = [System.Drawing.Color]::White

$titre = New-Object System.Windows.Forms.Label
$titre.Text = 'Capture planifiée du bureau'
$titre.Font = New-Object System.Drawing.Font('Segoe UI', 14, [System.Drawing.FontStyle]::Bold)
$titre.AutoSize = $true
$titre.Location = New-Object System.Drawing.Point(20, 16)
$form.Controls.Add($titre)

# Heure
$lblH = New-Object System.Windows.Forms.Label
$lblH.Text = 'Heure quotidienne (HH:mm) :'
$lblH.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$lblH.AutoSize = $true
$lblH.Location = New-Object System.Drawing.Point(22, 62)
$form.Controls.Add($lblH)

$txtH = New-Object System.Windows.Forms.TextBox
$txtH.Font = New-Object System.Drawing.Font('Segoe UI', 11)
$txtH.Text = '09:00'
$txtH.Size = New-Object System.Drawing.Size(90, 28)
$txtH.Location = New-Object System.Drawing.Point(230, 58)
$form.Controls.Add($txtH)

# Dossier
$lblD = New-Object System.Windows.Forms.Label
$lblD.Text = 'Dossier de destination :'
$lblD.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$lblD.AutoSize = $true
$lblD.Location = New-Object System.Drawing.Point(22, 104)
$form.Controls.Add($lblD)

$txtD = New-Object System.Windows.Forms.TextBox
$txtD.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$txtD.Text = $curDir
$txtD.Size = New-Object System.Drawing.Size(400, 28)
$txtD.Location = New-Object System.Drawing.Point(24, 130)
$form.Controls.Add($txtD)

$btnBrowse = New-Object System.Windows.Forms.Button
$btnBrowse.Text = '…'
$btnBrowse.Size = New-Object System.Drawing.Size(40, 26)
$btnBrowse.Location = New-Object System.Drawing.Point(432, 131)
$btnBrowse.Add_Click({
    $fb = New-Object System.Windows.Forms.FolderBrowserDialog
    $fb.Description = 'Choisir le dossier (ex. votre dossier Google Drive)'
    if (Test-Path $txtD.Text) { $fb.SelectedPath = $txtD.Text }
    if ($fb.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $txtD.Text = $fb.SelectedPath }
})
$form.Controls.Add($btnBrowse)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = "Astuce : pour l'envoyer sur Google Drive, installez « Google Drive pour ordinateur »" +
             "`npuis choisissez ici un dossier situé dans votre lecteur Google Drive."
$hint.Font = New-Object System.Drawing.Font('Segoe UI', 8.5)
$hint.ForeColor = [System.Drawing.Color]::DimGray
$hint.AutoSize = $false
$hint.Size = New-Object System.Drawing.Size(500, 40)
$hint.Location = New-Object System.Drawing.Point(24, 164)
$form.Controls.Add($hint)

# Boutons
$btnSave = New-Object System.Windows.Forms.Button
$btnSave.Text = 'Enregistrer la planification'
$btnSave.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$btnSave.Size = New-Object System.Drawing.Size(200, 34)
$btnSave.Location = New-Object System.Drawing.Point(24, 214)
$form.Controls.Add($btnSave)

$btnTest = New-Object System.Windows.Forms.Button
$btnTest.Text = 'Tester maintenant'
$btnTest.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$btnTest.Size = New-Object System.Drawing.Size(150, 34)
$btnTest.Location = New-Object System.Drawing.Point(236, 214)
$form.Controls.Add($btnTest)

$btnDel = New-Object System.Windows.Forms.Button
$btnDel.Text = 'Supprimer la planification'
$btnDel.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$btnDel.Size = New-Object System.Drawing.Size(200, 26)
$btnDel.Location = New-Object System.Drawing.Point(24, 258)
$form.Controls.Add($btnDel)

function Save-Config {
    $d = $txtD.Text.Trim()
    if ([string]::IsNullOrWhiteSpace($d)) { $d = $defaultDir }
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    Set-Content -Path $cfg -Value $d -Encoding UTF8
    return $d
}

$btnSave.Add_Click({
    $t = $txtH.Text.Trim()
    if ($t -notmatch '^([01]\d|2[0-3]):[0-5]\d$') {
        [System.Windows.Forms.MessageBox]::Show('Heure invalide. Format attendu : HH:mm (ex. 09:30).',
            'FaithBook', 'OK', 'Warning') | Out-Null
        return
    }
    if (-not (Test-Path $exe)) {
        [System.Windows.Forms.MessageBox]::Show("capture-bureau.exe est introuvable à côté de cet outil.",
            'FaithBook', 'OK', 'Error') | Out-Null
        return
    }
    $d = Save-Config
    $out = schtasks /Create /TN $TaskName /TR "`"$exe`"" /SC DAILY /ST $t /F 2>&1
    if ($LASTEXITCODE -eq 0) {
        [System.Windows.Forms.MessageBox]::Show(
            "Planifié : capture du bureau chaque jour à $t.`n`nDestination :`n$d",
            'FaithBook', 'OK', 'Information') | Out-Null
    } else {
        [System.Windows.Forms.MessageBox]::Show("Échec de la planification :`n$out",
            'FaithBook', 'OK', 'Error') | Out-Null
    }
})

$btnTest.Add_Click({
    $d = Save-Config
    $env:FAITHBOOK_TEST = '1'
    $res = & $exe 2>&1
    Remove-Item Env:\FAITHBOOK_TEST -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.MessageBox]::Show("Capture de test enregistrée dans :`n$d`n`n(sous-dossier du jour)",
        'FaithBook', 'OK', 'Information') | Out-Null
})

$btnDel.Add_Click({
    schtasks /Delete /TN $TaskName /F 2>&1 | Out-Null
    [System.Windows.Forms.MessageBox]::Show('Planification supprimée. La capture ne se fera plus automatiquement.',
        'FaithBook', 'OK', 'Information') | Out-Null
})

[void]$form.ShowDialog()
