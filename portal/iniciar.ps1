<#
.SYNOPSIS
  Arranca o portal SIVIT a partir de um clone limpo.
.DESCRIPTION
  1. Cria o .env a partir do .env.example, com segredos gerados (so se ainda nao existir).
  2. Constroi e arranca a pilha com "docker compose up" e espera que fique saudavel.
.PARAMETER Porta
  Porta do portal no anfitriao (so usada quando o .env e criado). Por defeito 8080.
.PARAMETER Projeto
  Nome do projeto Compose (opcional). Util para correr uma segunda pilha isolada.
.PARAMETER Forcar
  Recria o .env. Se ja existir um volume de dados, execute antes "docker compose down -v",
  porque a nova palavra-passe nao serve a base de dados ja inicializada.
.PARAMETER SoConfigurar
  Cria o .env mas nao arranca os contentores.
#>
param(
    [int]$Porta = 8080,
    [string]$Projeto = "",
    [switch]$Forcar,
    [switch]$SoConfigurar
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Novo-Segredo([int]$bytes) {
    $b = New-Object byte[] $bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($b)
    $rng.Dispose()
    return [Convert]::ToBase64String($b).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

# --- 1. .env ---------------------------------------------------------------
if ((Test-Path .env) -and -not $Forcar) {
    Write-Host "[iniciar] Ja existe um .env: vai ser reutilizado (use -Forcar para o recriar)."
}
else {
    if (-not (Test-Path .env.example)) { throw "Ficheiro .env.example nao encontrado em $PSScriptRoot" }
    if ($Forcar -and (Test-Path .env)) {
        Write-Host "[iniciar] AVISO: -Forcar gera novos segredos. Se ja existir um volume de dados,"
        Write-Host "          execute 'docker compose down -v' antes, ou a base de dados recusa a nova palavra-passe."
    }
    $chave = Novo-Segredo 50
    $senha = Novo-Segredo 18
    $linhas = Get-Content .env.example | ForEach-Object {
        if ($_ -like "DJANGO_SECRET_KEY=*") { "DJANGO_SECRET_KEY=$chave" }
        elseif ($_ -like "POSTGRES_PASSWORD=*") { "POSTGRES_PASSWORD=$senha" }
        elseif ($_ -like "PORTAL_PORT=*") { "PORTAL_PORT=$Porta" }
        else { $_ }
    }
    Set-Content .env $linhas -Encoding ascii
    Write-Host "[iniciar] .env criado com segredos gerados (nao vai para o Git)."
}

if ($SoConfigurar) { Write-Host "[iniciar] Configurado. Nada foi arrancado (-SoConfigurar)."; exit 0 }

# --- 2. Docker -------------------------------------------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "O comando 'docker' nao foi encontrado. Instale o Docker Desktop."
}
$eap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
docker info 2>&1 | Out-Null
$dockerOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $eap
if (-not $dockerOk) { throw "O Docker nao esta a correr. Abra o Docker Desktop, espere que fique ativo e tente de novo." }

# --- 3. Arranque -----------------------------------------------------------
$cmd = @()
if ($Projeto) { $cmd += @("-p", $Projeto) }
$cmd += @("up", "-d", "--build", "--wait", "--wait-timeout", "240")

Write-Host "[iniciar] A construir e a arrancar (a primeira vez demora alguns minutos)..."
docker compose @cmd
if ($LASTEXITCODE -ne 0) {
    Write-Host "[iniciar] O arranque falhou. Ultimas linhas do portal:"
    $logs = @()
    if ($Projeto) { $logs += @("-p", $Projeto) }
    $logs += @("logs", "portal", "--tail", "40")
    docker compose @logs
    exit 1
}

$portaFinal = ((Get-Content .env | Where-Object { $_ -like "PORTAL_PORT=*" }) -replace "^PORTAL_PORT=", "").Trim()
if (-not $portaFinal) { $portaFinal = "8080" }

Write-Host ""
Write-Host "[iniciar] Pronto: http://localhost:$portaFinal/"
Write-Host "[iniciar] Utilizadores de demonstracao e comandos uteis: ver README.md"