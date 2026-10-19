param(
    [int]$Duracao = 15,
    [int]$Concorrencia = 50,
    [int]$Lote = 10,
    [switch]$SoCache
)

function Reiniciar-Portal($latencia) {
    $env:LATENCIA_MS = "$latencia"
    docker compose up -d --no-deps --force-recreate portal 2>$null | Out-Null
    for ($i = 0; $i -lt 90; $i++) {
        docker compose exec -T portal python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/saude/', timeout=20)" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 1
    }
    throw "portal nao respondeu"
}

function Reiniciar-Ingestao($modo) {
    $env:MODO_VALIDACAO = $modo
    docker compose up -d --no-deps --force-recreate ingestao 2>$null | Out-Null
    for ($i = 0; $i -lt 60; $i++) {
        $codigo = curl.exe -s -o NUL -w '%{http_code}' http://localhost:8001/saude/pronto
        if ($codigo -eq "200") { return }
        Start-Sleep -Seconds 1
    }
    throw "ingestao nao ficou pronta"
}

function Executar-Carga($duracao, $conc = $Concorrencia) {
    $linhas = docker compose run --rm -T carga http://ingestao:8001/v1/leituras --metodo POST --lote $Lote --concorrencia $conc --duracao $duracao 2>$null
    $linhas | Where-Object { $_ -like '{*' } | Select-Object -Last 1 | ConvertFrom-Json
}

function Medir($rotulo, $modo, $latencia, $aquecer) {
    if ($aquecer) { Reiniciar-Portal 0 } else { Reiniciar-Portal $latencia }
    Reiniciar-Ingestao $modo
    if ($aquecer) {
        Executar-Carga 8 3 | Out-Null
        $e = Invoke-RestMethod http://localhost:8001/estado
        Write-Host "aquecimento: cache_entradas=$($e.cache_entradas) disjuntor=$($e.disjuntor)"
        if ($e.cache_entradas -lt 50) { throw "cache mal aquecida" }
        Reiniciar-Portal $latencia
    }
    $antes = Invoke-RestMethod http://localhost:8001/estado
    $r = Executar-Carga $Duracao
    $depois = Invoke-RestMethod http://localhost:8001/estado
    [pscustomobject]@{
        Configuracao = $rotulo
        Debito_req_s = $r.debito_req_s
        Leituras_perdidas = $r.leituras_perdidas
        p99_ms = $r.p99_ms
        Falhas_http = $r.erros_http + $r.falhas
        Retries = $depois.retries - $antes.retries
        Nao_validadas = $depois.nao_validadas - $antes.nao_validadas
        Disjuntor_rejeitadas = $depois.rejeitadas_disjuntor - $antes.rejeitadas_disjuntor
        Cache_hits = $depois.cache_hits - $antes.cache_hits
        Cache_entradas = $depois.cache_entradas
    }
}

$res = @()
if (-not $SoCache) {
    $res += Medir "Sincrona, portal saudavel" "sincrona" 0 $false
    $res += Medir "Sincrona, portal a 3 s" "sincrona" 3000 $false
    $res += Medir "+ timeout 500 ms" "timeout" 3000 $false
    $res += Medir "+ retry com backoff e jitter" "retry" 3000 $false
    $res += Medir "+ disjuntor" "disjuntor" 3000 $false
}
$res += Medir "+ cache local 60 s" "cache" 3000 $true

$res | Format-Table -AutoSize
$destino = if ($SoCache) { "..\docs\tp4_ex3_cache.csv" } else { "..\docs\tp4_ex3.csv" }
$res | Export-Csv -Path $destino -NoTypeInformation -Encoding ascii

Reiniciar-Portal 0
Remove-Item Env:MODO_VALIDACAO -ErrorAction SilentlyContinue
Remove-Item Env:LATENCIA_MS -ErrorAction SilentlyContinue
