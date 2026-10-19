$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$resultados = Join-Path $PSScriptRoot "resultados"
New-Item -ItemType Directory -Path $resultados -Force | Out-Null

$stdout = Join-Path $resultados "ex4_gateway_stdout.log"
$stderr = Join-Path $resultados "ex4_gateway_stderr.log"

Write-Host "A verificar a ingestao..."
$response = Invoke-WebRequest "http://localhost:8001/health/ready" -TimeoutSec 5 -UseBasicParsing
if ($response.StatusCode -ne 200) {
    throw "A ingestao nao esta pronta."
}

Write-Host "A iniciar o gateway..."
$argumentos = @(
    ".\gateway\gateway.py",
    "--alvo", "http://localhost:8001",
    "--dispositivos", "80",
    "--sensores", "4",
    "--frequencia", "1",
    "--duracao", "90",
    "--envio", "2",
    "--lote", "500",
    "--timeout", "2",
    "--drenar", "60",
    "--dir", ".\resultados\buffer"
)

$gateway = Start-Process -FilePath "python" `
    -ArgumentList $argumentos `
    -WorkingDirectory $PSScriptRoot `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

$parado = $false

try {
    Write-Host "A recolher leituras durante 20 segundos..."
    Start-Sleep -Seconds 20

    Write-Host "A interromper a ingestao durante 30 segundos..."
    docker compose stop ingestao
    $parado = $true
    Start-Sleep -Seconds 30

    Write-Host "A reiniciar a ingestao..."
    docker compose start ingestao

    $pronta = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        try {
            $r = Invoke-WebRequest "http://localhost:8001/health/ready" -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -eq 200) {
                $pronta = $true
                break
            }
        } catch {
            # A ingestao ainda esta a arrancar.
        }
    }

    if (-not $pronta) {
        throw "A ingestao nao recuperou dentro do tempo previsto."
    }

    $parado = $false
    Write-Host "Ingestao recuperada. A aguardar o gateway e o esvaziamento do buffer..."
    $gateway.WaitForExit()

    Write-Host "Gateway terminado com codigo: $($gateway.ExitCode)"
}
finally {
    if ($parado) {
        Write-Host "A garantir que a ingestao fica iniciada..."
        docker compose start ingestao
    }
}

Write-Host "`n--- Saida do gateway ---"
Get-Content $stdout -ErrorAction SilentlyContinue

Write-Host "`n--- Erros do gateway ---"
Get-Content $stderr -ErrorAction SilentlyContinue

Write-Host "`nLogs guardados em: $resultados"

