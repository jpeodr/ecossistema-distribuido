#!/usr/bin/env bash
# =============================================================================
# AgroData Distribuído — Configuração da Replicação MySQL Master -> Slaves
# =============================================================================
set -euo pipefail

# Carrega variáveis do .env se existir
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -v '^#' .env | sed 's/\r$//')
  set +a
fi

ROOT_PASS="${MYSQL_ROOT_PASSWORD:-rootpass}"
REPL_USER="${MYSQL_REPL_USER:-repl}"
REPL_PASS="${MYSQL_REPL_PASSWORD:-replpass}"
MASTER_CONTAINER="agrodata-mysql-master"
MASTER_HOST="mysql_master"
SLAVES=("agrodata-mysql-slave1" "agrodata-mysql-slave2" "agrodata-mysql-slave3")

echo "========================================================================"
echo " AgroData Distribuído — Configurando Replicação MySQL (GTID)"
echo "========================================================================"

wait_for_mysql() {
  local container="$1"
  echo -n "Aguardando ${container} ficar pronto"
  for _ in {1..60}; do
    if docker exec "${container}" mysqladmin ping -uroot -p"${ROOT_PASS}" --silent >/dev/null 2>&1; then
      echo " [OK]"
      return 0
    fi
    echo -n "."
    sleep 2
  done
  echo " [ERRO: timeout aguardando ${container}]"
  exit 1
}

# 1. Aguarda o Master e os 3 Slaves subirem
wait_for_mysql "${MASTER_CONTAINER}"
for slave in "${SLAVES[@]}"; do
  wait_for_mysql "${slave}"
done

# 2. Garante que o schema e usuários existam no Master (caso volume já existisse)
echo ""
echo "-> Garantindo schema e usuário de replicação no Master (${MASTER_CONTAINER})..."
docker exec -i "${MASTER_CONTAINER}" mysql -uroot -p"${ROOT_PASS}" < scripts/init_master.sql

# 3. Configura cada Slave para replicar do Master via GTID
for slave in "${SLAVES[@]}"; do
  echo ""
  echo "-> Configurando replicação em ${slave}..."

  # Garante estrutura base antes de iniciar a replicação e limpa estado GTID prévio
  docker exec -i "${slave}" mysql -uroot -p"${ROOT_PASS}" < scripts/init_master.sql

  docker exec "${slave}" mysql -uroot -p"${ROOT_PASS}" -e "
    STOP REPLICA;
    RESET REPLICA ALL;
    RESET MASTER;
    CHANGE REPLICATION SOURCE TO
      SOURCE_HOST='${MASTER_HOST}',
      SOURCE_PORT=3306,
      SOURCE_USER='${REPL_USER}',
      SOURCE_PASSWORD='${REPL_PASS}',
      SOURCE_AUTO_POSITION=1,
      GET_SOURCE_PUBLIC_KEY=1;
    START REPLICA;
    SET GLOBAL read_only = ON;
  "
done

# 4. Aguarda 2 segundos e verifica o status dos Slaves
sleep 2
echo ""
echo "========================================================================"
echo " Status da Replicação nos Slaves"
echo "========================================================================"

for slave in "${SLAVES[@]}"; do
  echo "--- ${slave} ---"
  docker exec "${slave}" mysql -uroot -p"${ROOT_PASS}" -e "SHOW REPLICA STATUS\G" \
    | grep -E "Replica_IO_State:|Source_Host:|Replica_IO_Running:|Replica_SQL_Running:|Seconds_Behind_Source:|Last_Error:" \
    || true
  echo ""
done

echo "Replicação configurada com sucesso!"

# 5. Teste opcional de replicação (--test)
if [[ "${1:-}" == "--test" ]]; then
  echo ""
  echo "========================================================================"
  echo " Testando Replicação: Inserindo registro no Master e lendo nos Slaves"
  echo "========================================================================"
  docker exec "${MASTER_CONTAINER}" mysql -uroot -p"${ROOT_PASS}" -D agrodata -e "
    INSERT INTO producao_agricola (uf, produto, periodo, producao, rendimento, area_plantada, area_colhida, worker_id)
    VALUES ('MT', 'soja', '2025', 45000000.00, 3600.00, 12500000.00, 12500000.00, 'test-replication')
    ON DUPLICATE KEY UPDATE
      producao = VALUES(producao),
      rendimento = VALUES(rendimento),
      area_plantada = VALUES(area_plantada),
      area_colhida = VALUES(area_colhida),
      worker_id = VALUES(worker_id);
  "
  sleep 1
  for slave in "${SLAVES[@]}"; do
    echo "--- Dados replicados em ${slave} ---"
    docker exec "${slave}" mysql -uroot -p"${ROOT_PASS}" -D agrodata -e "
      SELECT id, uf, produto, periodo, producao, rendimento, worker_id, coletado_em
      FROM producao_agricola
      WHERE worker_id = 'test-replication';
    "
  done
fi

