[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $CodexArgs
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    Write-Error "Codex CLI was not found on PATH. Install Codex and run 'codex login' before using this wrapper."
    exit 127
}

$BaseArgs = @(
    "exec",
    "--model", "gpt-5.5",
    "--config", 'model_reasoning_effort="xhigh"',
    "--config", 'approval_policy="never"',
    "--sandbox", "workspace-write",
    "--cd", $RepoRoot,
    "--ephemeral"
)

& codex @BaseArgs @CodexArgs
exit $LASTEXITCODE
