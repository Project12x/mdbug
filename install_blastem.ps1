param(
    [string]$InstallDir = (Join-Path $PSScriptRoot "blastem"),
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$version = "blastem-win64-0.6.3-pre-ec47c727cd65"
$zipName = "$version.zip"
$url = "https://www.retrodev.com/blastem/nightlies/$zipName"
$expectedSha256 = "076C6206C7E01C0E49195A277310B7181455CEEE7D8F3F270BF990B723DD655D"

$zipPath = Join-Path $InstallDir $zipName
$exePath = Join-Path $InstallDir "$version\blastem.exe"
$pathFile = Join-Path $InstallDir "path.txt"

if ((Test-Path -LiteralPath $exePath) -and -not $Force) {
    Write-Host "BlastEm already installed: $exePath"
    $resolvedExe = (Resolve-Path -LiteralPath $exePath).Path
    Set-Content -LiteralPath $pathFile -Value $resolvedExe -NoNewline
    Write-Host "BlastEm path written to: $pathFile"
    exit 0
}

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

Write-Host "Downloading BlastEm nightly $version..."
Invoke-WebRequest -Uri $url -OutFile $zipPath

$actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash
if ($actualSha256 -ne $expectedSha256) {
    throw "BlastEm zip hash mismatch. Expected $expectedSha256, got $actualSha256"
}

if (Test-Path -LiteralPath (Join-Path $InstallDir $version)) {
    Remove-Item -LiteralPath (Join-Path $InstallDir $version) -Recurse -Force
}

Expand-Archive -LiteralPath $zipPath -DestinationPath $InstallDir -Force

if (-not (Test-Path -LiteralPath $exePath)) {
    throw "BlastEm executable not found after extraction: $exePath"
}

$resolvedExe = (Resolve-Path -LiteralPath $exePath).Path
Set-Content -LiteralPath $pathFile -Value $resolvedExe -NoNewline
Write-Host "BlastEm installed: $exePath"
Write-Host "BlastEm path written to: $pathFile"
