# ============================================================
# Versao PowerShell do setup de replicacao (Windows).
# Uso:  powershell -ExecutionPolicy Bypass -File scripts/setup_replication.ps1
# ============================================================
$Master = "mysql_master"
$Slaves = @("mysql_slave1", "mysql_slave2", "mysql_slave3")
$RootPass = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { "rootpassword" }

Write-Host ">>> Aguardando o Master responder..."
do {
  docker exec -e MYSQL_PWD="$RootPass" $Master mysqladmin ping -h localhost --silent 2>$null
  if ($LASTEXITCODE -ne 0) { Start-Sleep -Seconds 2 }
} while ($LASTEXITCODE -ne 0)

# Garante o plugin de autenticacao compativel para o usuario de replicacao
docker exec -e MYSQL_PWD="$RootPass" $Master mysql -uroot -e "ALTER USER IF EXISTS 'repl'@'%' IDENTIFIED WITH mysql_native_password BY 'replpassword'; FLUSH PRIVILEGES;" 2>$null
Write-Host ">>> Master OK."

foreach ($Slave in $Slaves) {
  Write-Host ">>> Configurando replicacao em $Slave ..."
  do {
    docker exec -e MYSQL_PWD="$RootPass" $Slave mysqladmin ping -h localhost --silent 2>$null
    if ($LASTEXITCODE -ne 0) { Start-Sleep -Seconds 2 }
  } while ($LASTEXITCODE -ne 0)

  # Remove appuser local para evitar conflito com a replicacao do binlog do Master
  $sql = "STOP REPLICA; DROP USER IF EXISTS 'appuser'@'%'; CHANGE REPLICATION SOURCE TO SOURCE_HOST='$Master', SOURCE_USER='repl', SOURCE_PASSWORD='replpassword', SOURCE_AUTO_POSITION=1; START REPLICA;"
  docker exec -e MYSQL_PWD="$RootPass" $Slave mysql -uroot -e $sql 2>$null
  Write-Host ">>> $Slave configurado."
}

Write-Host ""
Write-Host ">>> Status da replicacao:"
foreach ($Slave in $Slaves) {
  Write-Host "--- $Slave ---"
  docker exec -e MYSQL_PWD="$RootPass" $Slave mysql -uroot -e "SHOW REPLICA STATUS\G" 2>$null | Select-String "Replica_IO_Running|Replica_SQL_Running|Seconds_Behind_Source"
}
Write-Host ""
Write-Host ">>> Replicacao ativa! IO e SQL threads devem estar em 'Yes'."
