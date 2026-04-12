# Growth Engine - Python Project Management Script

param(
    [Parameter(Mandatory = $false)]
    [ValidateSet('install', 'run', 'build', 'format', 'lint', 'test', 'clean', 'all')]
    [string]$Task = 'all'
    ,
    [Parameter(Mandatory = $false)]
    [switch]$NoBrowser
    ,
    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-StrictMode -Version Latest
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
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
        [string[]]$Arguments = @(),

        [Parameter(Mandatory = $false)]
        [switch]$Required
    )

    if (-not (Test-PythonModule -ModuleName $ModuleName)) {
        if ($Required) {
            throw "Required Python module '$ModuleName' is not installed."
        }

        Write-Host "Skipping $ModuleName because it is not installed." -ForegroundColor Yellow
        return
    }

    & python -m $ModuleName @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "python -m $ModuleName failed with exit code $LASTEXITCODE."
    }
}

function Install-Dependencies {
    Write-Host "Installing dependencies..." -ForegroundColor Cyan
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
}

function Run-Project {
    Write-Host "Starting web app in browser..." -ForegroundColor Cyan
    if (-not (Test-PythonModule -ModuleName "django")) {
        throw "Required Python module 'django' is not installed."
    }

    if (-not (Test-Path -LiteralPath "manage.py")) {
        throw "Could not find manage.py in $RepoRoot."
    }

    $appUrl = "http://localhost:$Port"
    Start-Process -FilePath "python" -ArgumentList @(
        "manage.py",
        "runserver",
        "localhost:$Port",
        "--noreload"
    ) | Out-Null

    Start-Sleep -Seconds 3
    if (-not $NoBrowser) {
        try {
            Start-Process $appUrl | Out-Null
        }
        catch {
            Write-Host "Django started, but opening the browser failed. Open $appUrl manually." -ForegroundColor Yellow
        }
    }
    Write-Host "App started at $appUrl" -ForegroundColor Green
}

function Build-Project {
    Write-Host "Running build-style verification..." -ForegroundColor Cyan
    python -m compileall app.py manage.py growth_engine growth_engine_django growth_engine_web tests
    if ($LASTEXITCODE -ne 0) {
        throw "compileall failed with exit code $LASTEXITCODE."
    }
}

function Format-Code {
    Write-Host "Formatting code..." -ForegroundColor Cyan
    Invoke-PythonModule -ModuleName "black" -Arguments @("app.py", "manage.py", "growth_engine", "growth_engine_django", "growth_engine_web", "tests", "scripts")
    Invoke-PythonModule -ModuleName "isort" -Arguments @("app.py", "manage.py", "growth_engine", "growth_engine_django", "growth_engine_web", "tests", "scripts", "--profile", "black")
}

function Lint-Code {
    Write-Host "Linting code..." -ForegroundColor Cyan
    Invoke-PythonModule -ModuleName "flake8" -Arguments @(
        "--max-line-length", "160",
        "growth_engine",
        "growth_engine_django",
        "growth_engine_web",
        "tests",
        "app.py",
        "manage.py"
    )
    python -m compileall app.py manage.py growth_engine growth_engine_django growth_engine_web tests
    if ($LASTEXITCODE -ne 0) {
        throw "compileall failed with exit code $LASTEXITCODE."
    }
}

function Test-Project {
    Write-Host "Running tests..." -ForegroundColor Cyan
    Invoke-PythonModule -ModuleName "pytest" -Arguments @("-q") -Required
}

function Clean-Project {
    Write-Host "Cleaning project..." -ForegroundColor Cyan
    Get-ChildItem -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("__pycache__", ".pytest_cache", ".pytest_tmp", "build", "dist") } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Recurse -File -Filter "*.pyc" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

# Execute tasks
try {
    switch ($Task) {
        'install' { Install-Dependencies }
        'run' { Run-Project }
        'build' { Build-Project }
        'format' { Format-Code }
        'lint' { Lint-Code }
        'test' { Test-Project }
        'clean' { Clean-Project }
        'all' {
            Install-Dependencies
            Format-Code
            Lint-Code
            Test-Project
            Build-Project
            Write-Host "Verification finished. Use -Task run to launch the UI." -ForegroundColor Green
        }
    }
    Write-Host "Task completed!" -ForegroundColor Green
}
finally {
    Pop-Location
}
