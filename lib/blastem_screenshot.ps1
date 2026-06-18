# Adapted from jazzmd/tools/capture_blastem_screenshot.ps1
# Replaces burst-with-brightest-frame selection with a multi-checkpoint loop.
# Each checkpoint @{ name=..; atSeconds=.. } triggers one screenshot at that
# elapsed time and saves it as "$OutDir\$name.png".
param(
    [Parameter(Mandatory=$true)][string]$EmuPath,
    [Parameter(Mandatory=$true)][string]$Rom,
    [Parameter(Mandatory=$true)][string]$OutDir,
    [hashtable[]]$Checkpoints = @()
)
$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$blastemDir = Split-Path -Parent $EmuPath
$cfg = Join-Path $blastemDir "default.cfg"
$cfgBackup = "$cfg.mdbugbak"

$shotDir = "C:\tmp\mdbug-shots"
$shotName = "mdbug-$([Guid]::NewGuid().ToString('N')).png"
$shotPath = Join-Path $shotDir $shotName

New-Item -ItemType Directory -Path $shotDir -Force | Out-Null

# Win32 interop: SetForegroundWindow + PostMessage (same as jazzmd)
if (-not ("Win32BlastEmMdbug" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class Win32BlastEmMdbug {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
}
'@
}

function Send-ScreenshotKey([IntPtr]$windowHandle) {
    # BlastEm screenshot key is 'P' (VK 0x50, scan 0x19) — same as jazzmd
    [Win32BlastEmMdbug]::PostMessage($windowHandle, 0x0100, [IntPtr]0x50, [IntPtr]0x00190001) | Out-Null
    Start-Sleep -Milliseconds 100
    [Win32BlastEmMdbug]::PostMessage($windowHandle, 0x0101, [IntPtr]0x50, [IntPtr]0xC0190001) | Out-Null
}

$process = $null

# Backup default.cfg and redirect screenshot_path / screenshot_template
Copy-Item -LiteralPath $cfg -Destination $cfgBackup -Force

try {
    $content = Get-Content -LiteralPath $cfg
    $content = $content -replace '^\s*screenshot_path\s+.*$',     "`tscreenshot_path C:/tmp/mdbug-shots"
    $content = $content -replace '^\s*screenshot_template\s+.*$', "`tscreenshot_template $shotName"
    Set-Content -LiteralPath $cfg -Value $content -Encoding ASCII

    $romPath = (Resolve-Path -LiteralPath $Rom).Path
    $argLine = "`"$romPath`" -g"
    $process = Start-Process -FilePath $EmuPath -ArgumentList $argLine `
        -WorkingDirectory $blastemDir -PassThru

    # Wait for the window handle to appear (mirrors jazzmd pattern)
    $process.Refresh()
    for ($i = 0; $i -lt 30 -and $process.MainWindowHandle -eq 0; $i++) {
        Start-Sleep -Milliseconds 250
        $process.Refresh()
    }
    if ($process.MainWindowHandle -eq 0) {
        throw "BlastEm window handle was not available."
    }

    [Win32BlastEmMdbug]::SetForegroundWindow($process.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 500

    $launchTime = [System.Diagnostics.Stopwatch]::StartNew()

    foreach ($cp in $Checkpoints) {
        $targetMs = [int]($cp.atSeconds * 1000)
        $elapsedMs = [int]$launchTime.Elapsed.TotalMilliseconds
        $waitMs = $targetMs - $elapsedMs
        if ($waitMs -gt 0) { Start-Sleep -Milliseconds $waitMs }

        # Ensure window is still foreground before capturing
        $process.Refresh()
        [Win32BlastEmMdbug]::SetForegroundWindow($process.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 100

        Remove-Item -LiteralPath $shotPath -Force -ErrorAction SilentlyContinue
        Send-ScreenshotKey $process.MainWindowHandle

        # Wait up to 10 s for the file to appear and be non-empty
        $appeared = $false
        for ($i = 0; $i -lt 40; $i++) {
            if ((Test-Path -LiteralPath $shotPath) -and
                ((Get-Item -LiteralPath $shotPath).Length -gt 0)) {
                $appeared = $true
                break
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $appeared) {
            throw "BlastEm did not create screenshot for checkpoint '$($cp.name)': $shotPath"
        }

        $destPath = Join-Path $OutDir "$($cp.name).png"
        Copy-Item -LiteralPath $shotPath -Destination $destPath -Force
        Write-Host "Checkpoint '$($cp.name)': saved $destPath"
    }
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $cfgBackup) {
        Move-Item -LiteralPath $cfgBackup -Destination $cfg -Force
    }
}
