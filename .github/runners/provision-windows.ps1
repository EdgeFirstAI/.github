# Provision an ephemeral Windows GitHub Actions runner.
# Labels: self-hosted, windows, x64, d3d11
#
# Required env: RUNNER_TOKEN
# Optional: GITHUB_ORG, RUNNER_NAME, RUNNER_LABELS, RUNNER_GROUP, WORKDIR, RUNNER_VERSION

$ErrorActionPreference = "Stop"

$GithubOrg = if ($env:GITHUB_ORG) { $env:GITHUB_ORG } else { "EdgeFirstAI" }
$Workdir = if ($env:WORKDIR) { $env:WORKDIR } else { "C:\actions-runner" }
$RunnerName = if ($env:RUNNER_NAME) { $env:RUNNER_NAME } else { "$env:COMPUTERNAME-win" }
$RunnerLabels = if ($env:RUNNER_LABELS) { $env:RUNNER_LABELS } else { "self-hosted,windows,x64,d3d11" }
$RunnerGroup = if ($env:RUNNER_GROUP) { $env:RUNNER_GROUP } else { "windows" }
$Version = if ($env:RUNNER_VERSION) { $env:RUNNER_VERSION } else { "2.328.0" }

if (-not $env:RUNNER_TOKEN) {
    throw "RUNNER_TOKEN is required"
}

New-Item -ItemType Directory -Force -Path $Workdir | Out-Null
Set-Location $Workdir

if (-not (Test-Path .\config.cmd)) {
    $tarball = "actions-runner-win-x64-$Version.zip"
    Invoke-WebRequest -Uri "https://github.com/actions/runner/releases/download/v$Version/$tarball" -OutFile $tarball
    Expand-Archive -Path $tarball -DestinationPath . -Force
}

& .\config.cmd --unattended --replace `
    --url "https://github.com/$GithubOrg" `
    --token $env:RUNNER_TOKEN `
    --name $RunnerName `
    --labels $RunnerLabels `
    --runnergroup $RunnerGroup `
    --work _work `
    --ephemeral

& .\run.cmd
