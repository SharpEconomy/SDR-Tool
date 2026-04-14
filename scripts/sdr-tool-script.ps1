param(
    [Parameter(Mandatory = $false)]
    [switch]$NoBrowser,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ScriptPath = $MyInvocation.MyCommand.Path
Push-Location $RepoRoot

function Test-PythonModule {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ModuleName
    )

    $null = python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)"
    return $LASTEXITCODE -eq 0
}

function Invoke-PythonModule {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ModuleName,

        [Parameter(Mandatory = $false)]
        [string[]]$Arguments = @()
    )

    & python -m $ModuleName @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "python -m $ModuleName failed with exit code $LASTEXITCODE."
    }
}

function Install-ProjectDependencies {
    Write-Host "Installing dependencies..." -ForegroundColor Cyan
    python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip."
    }

    python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install project dependencies."
    }
}

function Ensure-ProjectDependencies {
    $requiredModules = @("black", "django", "flake8", "isort", "pytest")
    $missingModules = @(
        $requiredModules | Where-Object { -not (Test-PythonModule -ModuleName $_) }
    )

    if ($missingModules.Count -eq 0) {
        Write-Host "Dependencies already available." -ForegroundColor Green
        return
    }

    Write-Host "Missing Python modules detected: $($missingModules -join ', ')" -ForegroundColor Yellow
    Install-ProjectDependencies
}

function Get-ListeningProcessId {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $connection) {
        return $null
    }

    return [int]$connection.OwningProcess
}

function Get-ProtectedProcessIds {
    $protectedIds = [System.Collections.Generic.HashSet[int]]::new()
    $processId = $PID

    while ($processId -gt 0 -and $protectedIds.Add($processId)) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            break
        }

        $processId = [int]$process.ParentProcessId
    }

    return $protectedIds
}

function Add-ProjectShellAncestors {
    param(
        [Parameter(Mandatory = $true)]
        [int]$RootProcessId,

        [Parameter(Mandatory = $true)]
        [System.Collections.Generic.HashSet[int]]$TargetIds,

        [Parameter(Mandatory = $true)]
        [System.Collections.Generic.HashSet[int]]$ProtectedIds
    )

    $shellNames = @("powershell.exe", "pwsh.exe", "cmd.exe")
    $visited = [System.Collections.Generic.HashSet[int]]::new()
    $processId = $RootProcessId

    while ($processId -gt 0 -and $visited.Add($processId)) {
        if (-not $ProtectedIds.Contains($processId)) {
            $null = $TargetIds.Add($processId)
        }

        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            break
        }

        $parentProcessId = [int]$process.ParentProcessId
        if ($parentProcessId -le 0) {
            break
        }

        $parentProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $parentProcessId" -ErrorAction SilentlyContinue
        if ($null -eq $parentProcess) {
            break
        }

        if ($shellNames -notcontains $parentProcess.Name.ToLowerInvariant()) {
            break
        }

        $processId = $parentProcessId
    }
}

function Get-ProjectSessionProcessIds {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $protectedIds = Get-ProtectedProcessIds
    $targetIds = [System.Collections.Generic.HashSet[int]]::new()

    $listeningProcessId = Get-ListeningProcessId -Port $Port
    if ($null -ne $listeningProcessId) {
        Add-ProjectShellAncestors -RootProcessId $listeningProcessId -TargetIds $targetIds -ProtectedIds $protectedIds
    }

    $managePath = Join-Path $RepoRoot "manage.py"
    $candidateProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $commandLine = $_.CommandLine
        if ([string]::IsNullOrWhiteSpace($commandLine)) {
            return $false
        }

        if ($protectedIds.Contains([int]$_.ProcessId)) {
            return $false
        }

        $processName = $_.Name.ToLowerInvariant()
        $referencesProject = $commandLine -like "*$ScriptPath*" -or $commandLine -like "*$managePath*"
        $isProjectShell = $processName -in @("powershell.exe", "pwsh.exe", "cmd.exe")
        $isProjectPython = $processName -in @("python.exe", "pythonw.exe", "py.exe")

        return $referencesProject -and ($isProjectShell -or $isProjectPython)
    }

    foreach ($process in $candidateProcesses) {
        Add-ProjectShellAncestors -RootProcessId ([int]$process.ProcessId) -TargetIds $targetIds -ProtectedIds $protectedIds
    }

    return @($targetIds)
}

function Stop-ProjectSessions {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $processIds = @(Get-ProjectSessionProcessIds -Port $Port | Sort-Object -Descending -Unique)
    if ($processIds.Count -eq 0) {
        Write-Host "No other project terminal or server process was found." -ForegroundColor Yellow
        return
    }

    foreach ($processId in $processIds) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            continue
        }

        Write-Host "Stopping process $($process.ProcessName) (PID $processId)..." -ForegroundColor Cyan
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Seconds 1
}

function Clear-PythonCaches {
    Write-Host "Clearing Python bytecode caches..." -ForegroundColor Cyan
    Get-ChildItem -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "__pycache__" } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Recurse -File -Filter "*.pyc" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

function Invoke-LintChecks {
    Write-Host "Running lint checks..." -ForegroundColor Cyan
    Invoke-PythonModule -ModuleName "flake8" -Arguments @(
        "--jobs", "1",
        "--max-line-length", "160",
        "growth_engine",
        "growth_engine_django",
        "growth_engine_web",
        "tests",
        "app.py",
        "manage.py"
    )
}

function Invoke-TestSuite {
    Write-Host "Running test suite..." -ForegroundColor Cyan
    Invoke-PythonModule -ModuleName "pytest" -Arguments @("-q")
}

function Invoke-BuildChecks {
    Write-Host "Running build/compile checks..." -ForegroundColor Cyan
    python -m compileall app.py manage.py growth_engine growth_engine_django growth_engine_web tests
    if ($LASTEXITCODE -ne 0) {
        throw "compileall failed with exit code $LASTEXITCODE."
    }
}

function Invoke-CodeFormat {
    Write-Host "Running import sorting..." -ForegroundColor Cyan
    Invoke-PythonModule -ModuleName "isort" -Arguments @(
        "growth_engine",
        "growth_engine_django",
        "growth_engine_web",
        "tests",
        "app.py",
        "manage.py"
    )

    Write-Host "Running code formatting..." -ForegroundColor Cyan
    Invoke-PythonModule -ModuleName "black" -Arguments @(
        "growth_engine",
        "growth_engine_django",
        "growth_engine_web",
        "tests",
        "app.py",
        "manage.py"
    )
}

function Open-BrowserAsync {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    $escapedUrl = $Url.Replace("'", "''")
    Start-Process -FilePath "powershell" -ArgumentList @(
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-Command",
        "Start-Sleep -Seconds 2; Start-Process '$escapedUrl'"
    ) | Out-Null
}

try {
    if (-not (Test-Path -LiteralPath "manage.py")) {
        throw "Could not find manage.py in $RepoRoot."
    }

    Ensure-ProjectDependencies
    Stop-ProjectSessions -Port $Port
    Clear-PythonCaches
    Invoke-CodeFormat
    Invoke-LintChecks
    Invoke-TestSuite
    Invoke-BuildChecks

    $appUrl = "http://localhost:$Port"
    if (-not $NoBrowser) {
        Open-BrowserAsync -Url $appUrl
    }

    Write-Host "Starting Django at $appUrl" -ForegroundColor Green
    Write-Host "Press Ctrl+C to stop the server." -ForegroundColor DarkGray

    & python manage.py runserver "localhost:$Port" --noreload
    if ($LASTEXITCODE -ne 0) {
        throw "Django exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
