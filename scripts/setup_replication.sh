#!/usr/bin/env bash
# ============================================================
# Configura a replicacao Master -> Slaves via GTID.
# Execute APOS subir os containers (docker compose up -d).
# Uso:  bash scripts/setup_replication.sh
# ============================================================
set -e

MASTER="mysql_master"
SLAVES=("mysql_slave1" "mysql_slave2" "mysql_slave3")
ROOT_PASS="${MYSQL_ROOT_PASSWORD:-rootpassword}"

echo ">>> Aguardando o Master responder..."
until docker exec -e MYSQL_PWD="$ROOT_PASS" "$MASTER" mysqladmin ping -h localhost --silent; do
  sleep 2
done

docker exec -e MYSQL_PWD="$ROOT_PASS" "$MASTER" mysql -uroot -e \
  "ALTER USER IF EXISTS 'repl'@'%' IDENTIFIED WITH mysql_native_password BY 'replpassword'; FLUSH PRIVILEGES;"
echo ">>> Master OK."

for SLAVE in "${SLAVES[@]}"; do
  echo ">>> Configurando replicacao em $SLAVE ..."
  until docker exec -e MYSQL_PWD="$ROOT_PASS" "$SLAVE" mysqladmin ping -h localhost --silent; do
    sleep 2
  done
  docker exec -e MYSQL_PWD="$ROOT_PASS" "$SLAVE" mysql -uroot -e "
    STOP REPLICA;
    DROP USER IF EXISTS 'appuser'@'%';
    CHANGE REPLICATION SOURCE TO
      SOURCE_HOST='$MASTER',
      SOURCE_USER='repl',
      SOURCE_PASSWORD='replpassword',
      SOURCE_AUTO_POSITION=1;
    START REPLICA;
  "
  echo ">>> $SLAVE configurado."
done

echo ""
echo ">>> Status da replicacao:"
for SLAVE in "${SLAVES[@]}"; do
  echo "--- $SLAVE ---"
  docker exec -e MYSQL_PWD="$ROOT_PASS" "$SLAVE" mysql -uroot -e \
    "SHOW REPLICA STATUS\G" | grep -E "Replica_IO_Running|Replica_SQL_Running|Seconds_Behind_Source"
done
echo ""
echo ">>> Replicacao ativa! IO e SQL threads devem estar em 'Yes'."
