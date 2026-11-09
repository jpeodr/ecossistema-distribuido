# =============================================================================
# AgroData Distribuído — Configuração da Replicação MySQL Master -> Slaves
# Script para Windows PowerShell
# =============================================================================
param(
    [switch]$Test
)

$ErrorActionPreference = "Stop"

# Carrega variáveis do .env se existir
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            [System.Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
        }
    }
}

$RootPass = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { "rootpass" }
$ReplUser = if ($env:MYSQL_REPL_USER) { $env:MYSQL_REPL_USER } else { "repl" }
$ReplPass = if ($env:MYSQL_REPL_PASSWORD) { $env:MYSQL_REPL_PASSWORD } else { "replpass" }
$MasterContainer = "agrodata-mysql-master"
$MasterHost = "mysql_master"
$Slaves = @("agrodata-mysql-slave1", "agrodata-mysql-slave2", "agrodata-mysql-slave3")

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host " AgroData Distribuído — Configurando Replicação MySQL (GTID)" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan

function Wait-MySqlReady {
    param([string]$Container)
    Write-Host -NoNewline "Aguardando $Container ficar pronto"
    for ($i = 0; $i -lt 60; $i++) {
        $null = docker exec $Container mysqladmin ping -uroot -p"$RootPass" --silent 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host " [OK]" -ForegroundColor Green
            return
        }
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 2
    }
    Write-Host " [ERRO: timeout aguardando $Container]" -ForegroundColor Red
    exit 1
}

# 1. Aguarda o Master e os 3 Slaves subirem
Wait-MySqlReady -Container $MasterContainer
foreach ($slave in $Slaves) {
    Wait-MySqlReady -Container $slave
}

# 2. Garante que o schema e usuários existam no Master
Write-Host "`n-> Garantindo schema e usuário de replicação no Master ($MasterContainer)..." -ForegroundColor Yellow
Get-Content -Raw "scripts/init_master.sql" | docker exec -i $MasterContainer mysql -uroot -p"$RootPass"

# 3. Configura cada Slave para replicar do Master via GTID
foreach ($slave in $Slaves) {
    Write-Host "`n-> Configurando replicação em $slave..." -ForegroundColor Yellow

    Get-Content -Raw "scripts/init_master.sql" | docker exec -i $slave mysql -uroot -p"$RootPass"

    $sql = @"
STOP REPLICA;
RESET REPLICA ALL;
RESET MASTER;
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='$MasterHost',
  SOURCE_PORT=3306,
  SOURCE_USER='$ReplUser',
  SOURCE_PASSWORD='$ReplPass',
  SOURCE_AUTO_POSITION=1,
  GET_SOURCE_PUBLIC_KEY=1;
START REPLICA;
SET GLOBAL read_only = ON;
"@
    docker exec $slave mysql -uroot -p"$RootPass" -e $sql
}

# 4. Aguarda sincronização inicial e exibe o status dos Slaves
Start-Sleep -Seconds 2
Write-Host "`n========================================================================" -ForegroundColor Cyan
Write-Host " Status da Replicação nos Slaves" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan

foreach ($slave in $Slaves) {
    Write-Host "--- $slave ---" -ForegroundColor Green
    $status = docker exec $slave mysql -uroot -p"$RootPass" -e "SHOW REPLICA STATUS\G" 2>$null
    $status | Select-String -Pattern "Replica_IO_State:|Source_Host:|Replica_IO_Running:|Replica_SQL_Running:|Seconds_Behind_Source:|Last_Error:" | ForEach-Object {
        Write-Host $_.Line
    }
    Write-Host ""
}

Write-Host "Replicação configurada com sucesso!" -ForegroundColor Green

# 5. Teste opcional de replicação (-Test)
if ($Test) {
    Write-Host "`n========================================================================" -ForegroundColor Cyan
    Write-Host " Testando Replicação: Inserindo registro no Master e lendo nos Slaves" -ForegroundColor Cyan
    Write-Host "========================================================================" -ForegroundColor Cyan

    $insertSql = @"
INSERT INTO producao_agricola (uf, produto, periodo, producao, rendimento, area_plantada, area_colhida, worker_id)
VALUES ('MT', 'soja', '2025', 45000000.00, 3600.00, 12500000.00, 12500000.00, 'test-replication')
ON DUPLICATE KEY UPDATE
  producao = VALUES(producao),
  rendimento = VALUES(rendimento),
  area_plantada = VALUES(area_plantada),
  area_colhida = VALUES(area_colhida),
  worker_id = VALUES(worker_id);
"@
    docker exec $MasterContainer mysql -uroot -p"$RootPass" -D agrodata -e $insertSql
    Start-Sleep -Seconds 1

    foreach ($slave in $Slaves) {
        Write-Host "--- Dados replicados em $slave ---" -ForegroundColor Green
        docker exec $slave mysql -uroot -p"$RootPass" -D agrodata -e "SELECT id, uf, produto, periodo, producao, rendimento, worker_id, coletado_em FROM producao_agricola WHERE worker_id = 'test-replication';"
    }
}

