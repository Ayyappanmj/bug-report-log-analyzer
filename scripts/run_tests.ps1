# Windows PowerShell helper. Usage:  .\scripts\run_tests.ps1 [-Fast] [-Coverage]
param([switch]$Fast, [switch]$Coverage)
$args_ = @()
if ($Fast) { $args_ += @("-m", "not slow") }
if ($Coverage) { $args_ += @("--cov=.", "--cov-report=term-missing") }
python -m pytest @args_
