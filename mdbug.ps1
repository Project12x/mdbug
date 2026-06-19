param(
    [Parameter(Mandatory=$true)][string]$Config,
    [string]$Backend,
    [switch]$NoBuild,
    [switch]$NoScreenshots,
    [switch]$UpdateBaseline,
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$Config = (Resolve-Path -LiteralPath $Config).Path
$cfg = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
$cfgDir = Split-Path (Resolve-Path -LiteralPath $Config) -Parent
if (-not $Backend) { $Backend = $cfg.backends.default }
$be = $cfg.backends.$Backend
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }

function Resolve-RepoPath([string]$p) {
    if ([System.IO.Path]::IsPathRooted($p)) { return $p }
    return [System.IO.Path]::GetFullPath((Join-Path $cfgDir $p))
}

$widthLetter = switch ($cfg.perf.width) { "u8" { "bu" } "u32" { "wu" } default { "hu" } }

# build root: where the build runs and emits rom/elf/symbol
$buildCwd = if ($cfg.build -and $cfg.build.cwd) { Resolve-RepoPath $cfg.build.cwd } else { $cfgDir }
function Resolve-BuildPath([string]$p) {
    if ([System.IO.Path]::IsPathRooted($p)) { return $p }
    return [System.IO.Path]::GetFullPath((Join-Path $buildCwd $p))
}

# 1. build
if (-not $NoBuild -and $cfg.build.command) {
    if ($DryRun) {
        Write-Output "BUILD: $($cfg.build.command)  (cwd=$buildCwd)"
    } else {
        # Put the build dir on PATH so the build command is found even when the
        # shell excludes the current directory from executable search.
        $savedPath = $env:PATH
        $env:PATH = "$buildCwd;$env:PATH"
        try {
            $bp = Start-Process -FilePath "cmd.exe" -ArgumentList "/c $($cfg.build.command)" -WorkingDirectory $buildCwd -NoNewWindow -Wait -PassThru
            if ($bp.ExitCode -ne 0) { throw "build failed (exit $($bp.ExitCode))" }
        } finally { $env:PATH = $savedPath }
    }
}

$rom = Resolve-BuildPath $cfg.build.rom
$elf = Resolve-BuildPath $cfg.build.elf

# 2. resolve perf block address from the ELF symbol table (export mode)
$address = 0
$symFile = Join-Path (Split-Path -Parent $elf) "symbol.txt"
if (Test-Path -LiteralPath $symFile) {
    $address = [int64](& $python -c "import sys; sys.path.insert(0, sys.argv[3]); from analyzer.config import resolve_symbol_address as r; print(r(open(sys.argv[1]).read(), sys.argv[2]))" $symFile $cfg.perf.symbol $here)
}
# export mode dumps from a raw address; refuse to silently dump from 0x000000
if (-not $DryRun -and $Backend -eq "emusplatter" -and $be.sampleMode -eq "export" -and $address -eq 0) {
    throw "mdbug: could not resolve perf symbol '$($cfg.perf.symbol)' address from $symFile (export mode requires the symbol table). Build the ROM first or check build.elf."
}

$outDir = Resolve-RepoPath $cfg.report.outDir
$dump = Join-Path $outDir "samples.txt"
$shotsDir = Join-Path $outDir "shots"

# 3. checkpoints
$checkpoints = @()
if ($cfg.screenshots -and $cfg.screenshots.enabled) {
    foreach ($c in $cfg.screenshots.checkpoints) {
        $checkpoints += @{ name = $c.name; atSeconds = $c.atSeconds; atFrame = $c.atFrame }
    }
}

# 4. resolve gdb (for GDB-sampling backends)
$gdb = $be.gdb
if (-not $gdb) {
    if ($env:GDK -and (Test-Path (Join-Path $env:GDK "bin\gdb.exe"))) { $gdb = Join-Path $env:GDK "bin\gdb.exe" }
    elseif (Test-Path "C:\SDKs\SGDK\bin\gdb.exe") { $gdb = "C:\SDKs\SGDK\bin\gdb.exe" }
}

$preroll = [string[]]@()
if ($cfg.perf.preroll) { $preroll = [string[]]@($cfg.perf.preroll) }

if (-not $DryRun) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }

# 5. sample pass
$adapter = Join-Path $here "backends\$Backend.ps1"
$sampleArgs = @{
    Action = "sample"; Rom = $rom; Elf = $elf; EmuPath = $be.path
    Symbol = $cfg.perf.symbol; Count = $cfg.perf.count; WidthLetter = $widthLetter
    TriggerSymbol = $cfg.perf.trigger.symbol; Preroll = $preroll; Samples = $cfg.perf.samples
    DoneSymbol = $cfg.perf.doneFlag.symbol; OutFile = $dump; Gdb = $gdb; Port = $be.gdbPort
}
if ($Backend -eq "emusplatter") {
    $sampleArgs.SampleMode = $be.sampleMode
    $sampleArgs.Frames = $be.frames
    $sampleArgs.Address = $address
}
if ($DryRun) { $sampleArgs.DryRun = $true }
& $adapter @sampleArgs

# 6. screenshot pass
if (-not $NoScreenshots -and $checkpoints.Count -gt 0) {
    $shotArgs = @{ Action = "screenshot"; Rom = $rom; EmuPath = $be.path; OutFile = $shotsDir; Checkpoints = $checkpoints }
    if ($DryRun) { $shotArgs.DryRun = $true }
    & $adapter @shotArgs
}

# 7. analyze + gate
$fmt = if ($Backend -eq "emusplatter" -and $be.sampleMode -eq "export") { "export" } else { "gdb" }
$sha = (git -C $cfgDir rev-parse --short HEAD 2>$null)
if (-not $sha) { $sha = "?" }
$analyzeArgs = @("-m", "analyzer.cli", "--config", $Config, "--backend", $Backend,
    "--samples-file", $dump, "--samples-format", $fmt, "--shots-dir", $shotsDir,
    "--out", (Join-Path $outDir "report.md"), "--git-sha", $sha, "--project", (Split-Path $buildCwd -Leaf))
if ($UpdateBaseline) { $analyzeArgs += "--update-baseline" }
if ($DryRun) { Write-Output "ANALYZE: $python $($analyzeArgs -join ' ')"; return }

Push-Location $here
try { & $python @analyzeArgs; $rc = $LASTEXITCODE } finally { Pop-Location }
exit $rc
