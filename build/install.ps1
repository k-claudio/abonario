# Instala o Abonário para o usuário atual (sem privilégios de administrador).
# Move (não copia) o programa e o banco, para economizar disco, e cria atalhos.
param(
    [string]$Dist = (Join-Path $PSScriptRoot "..\dist\Abonario"),
    [string]$Db = (Join-Path $PSScriptRoot "..\data\abonario.db"),
    [string]$AuleteCache = (Join-Path $PSScriptRoot "..\data\aulete_cache.db"),
    [string]$Target = (Join-Path $env:LOCALAPPDATA "Programs\Abonario")
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path (Join-Path $Dist "Abonario.exe"))) { throw "Executável não encontrado em $Dist" }
New-Item -ItemType Directory -Force -Path $Target | Out-Null

# programa (substitui versão anterior, preservando os bancos já instalados se não houver novos)
Get-ChildItem -Path $Target -Exclude "abonario.db", "aulete_cache.db" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $Dist | Move-Item -Destination $Target -Force

if (Test-Path $Db) {
    Move-Item -Path $Db -Destination (Join-Path $Target "abonario.db") -Force
}
if (-not (Test-Path (Join-Path $Target "abonario.db"))) { throw "Banco abonario.db ausente" }

$hasAulete = $false
if (Test-Path $AuleteCache) {
    Move-Item -Path $AuleteCache -Destination (Join-Path $Target "aulete_cache.db") -Force
    $hasAulete = $true
} elseif (Test-Path (Join-Path $Target "aulete_cache.db")) {
    $hasAulete = $true
}
Remove-Item -Path (Join-Path $Target "aulete_cache.db-wal"), (Join-Path $Target "aulete_cache.db-shm") -Force -ErrorAction SilentlyContinue

$exe = Join-Path $Target "Abonario.exe"
$shell = New-Object -ComObject WScript.Shell
$links = @(
    (Join-Path ([Environment]::GetFolderPath("Programs")) "Abonário.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "Abonário.lnk")
)
foreach ($l in $links) {
    $s = $shell.CreateShortcut($l)
    $s.TargetPath = $exe
    $s.WorkingDirectory = $Target
    $s.IconLocation = "$exe,0"
    $s.Description = "Dicionário da língua portuguesa com abonações (offline)"
    $s.Save()
}
Write-Output "Instalado em $Target"
Write-Output ("Cache Aulete: " + $(if ($hasAulete) { "incluído (aulete_cache.db)" } else { "ausente (será preenchido sob demanda)" }))
Write-Output ("Tamanho: {0:N0} MB" -f ((Get-ChildItem $Target -Recurse | Measure-Object Length -Sum).Sum / 1MB))
