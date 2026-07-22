# ============================================================================
#  Capture d'écran du bureau Windows (tous les moniteurs) → PNG daté.
#  Exécuté par le Planificateur de tâches à l'heure choisie. Compilé en
#  capture-bureau.exe (sans console). Le dossier de destination est lu dans
#  bureau.config.txt (à côté), sinon un dossier local par défaut.
# ============================================================================
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# --- Dossier de l'outil (exe ou script) --------------------------------------
if ($PSScriptRoot) {
    $base = $PSScriptRoot
} else {
    $base = Split-Path -Parent ([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)
}

# --- Dossier de destination (configurable) -----------------------------------
$cfg = Join-Path $base 'bureau.config.txt'
$outDir = ''
if (Test-Path $cfg) { $outDir = (Get-Content $cfg -Raw -Encoding UTF8).Trim() }
if ([string]::IsNullOrWhiteSpace($outDir)) {
    $outDir = Join-Path $env:USERPROFILE 'FaithBook-captures\bureau'
}

# --- Capture de l'ensemble des écrans (bureau virtuel) -----------------------
try {
    $vs  = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object System.Drawing.Bitmap($vs.Width, $vs.Height)
    $g   = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($vs.Location, [System.Drawing.Point]::Empty, $vs.Size)
    $g.Dispose()

    $day   = Get-Date -Format 'yyyy-MM-dd'
    $stamp = Get-Date -Format 'HHmmss'
    $dir   = Join-Path $outDir $day
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $file  = Join-Path $dir ("{0}_bureau_{1}.png" -f $day, $stamp)
    $bmp.Save($file, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()

    # Journal simple à côté de l'outil.
    $line = "{0}  OK  {1}x{2}  {3}" -f (Get-Date -Format 's'), $vs.Width, $vs.Height, $file
    Add-Content -Path (Join-Path $base 'capture-bureau.log') -Value $line -Encoding UTF8

    # En mode test, on renvoie le chemin sur la sortie standard.
    if ($env:FAITHBOOK_TEST -eq '1') { Write-Output $file }
    exit 0
}
catch {
    $err = "{0}  ERREUR  {1}" -f (Get-Date -Format 's'), $_.Exception.Message
    Add-Content -Path (Join-Path $base 'capture-bureau.log') -Value $err -Encoding UTF8
    if ($env:FAITHBOOK_TEST -eq '1') { Write-Output "ERREUR: $($_.Exception.Message)" }
    exit 1
}
