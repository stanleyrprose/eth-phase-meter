#!/usr/bin/env bash
set -euo pipefail

PG_MAJOR="${PG_MAJOR:-18}"
DB_NAME="${DB_NAME:-eth_phase_meter}"
DB_USER="${DB_USER:-eth_phase_meter}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: provision_bkk_postgres.sh must run as root" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y ca-certificates curl postgresql-common

install -d -m 0755 /usr/share/postgresql-common/pgdg
curl -fsSL   https://www.postgresql.org/media/keys/ACCC4CF8.asc   -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc

. /etc/os-release
arch="$(dpkg --print-architecture)"
cat > /etc/apt/sources.list.d/pgdg.sources <<EOF
Types: deb
URIs: https://apt.postgresql.org/pub/repos/apt
Suites: ${VERSION_CODENAME}-pgdg
Architectures: ${arch}
Components: main
Signed-By: /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
EOF

apt-get update
apt-get install -y "postgresql-${PG_MAJOR}" "postgresql-client-${PG_MAJOR}"

conf="/etc/postgresql/${PG_MAJOR}/main/postgresql.conf"
hba="/etc/postgresql/${PG_MAJOR}/main/pg_hba.conf"

if [[ ! -f "${conf}" || ! -f "${hba}" ]]; then
  echo "ERROR: PostgreSQL ${PG_MAJOR} cluster configuration not found" >&2
  exit 1
fi

sed -ri "s/^#?listen_addresses\s*=.*/listen_addresses = '127.0.0.1'/" "${conf}"
sed -ri "s/^#?max_connections\s*=.*/max_connections = 30/" "${conf}"
sed -ri "s/^#?shared_buffers\s*=.*/shared_buffers = 128MB/" "${conf}"
sed -ri "s/^#?work_mem\s*=.*/work_mem = 4MB/" "${conf}"
sed -ri "s/^#?maintenance_work_mem\s*=.*/maintenance_work_mem = 64MB/" "${conf}"

trust_line="hostnossl ${DB_NAME} ${DB_USER} 127.0.0.1/32 trust"
if ! grep -Fqx "${trust_line}" "${hba}"; then
  tmp="$(mktemp)"
  {
    echo "# ETH Phase Meter: SSH-tunnel-only local TCP access"
    echo "${trust_line}"
    cat "${hba}"
  } > "${tmp}"
  install -m 0640 -o postgres -g postgres "${tmp}" "${hba}"
  rm -f "${tmp}"
fi

systemctl enable postgresql
systemctl restart postgresql

if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c     "CREATE ROLE ${DB_USER} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;"
fi

if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  runuser -u postgres -- createdb -O "${DB_USER}" "${DB_NAME}"
fi

runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c   "ALTER DATABASE ${DB_NAME} OWNER TO ${DB_USER};"
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c   "ALTER ROLE ${DB_USER} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;"

systemctl restart postgresql

echo "PostgreSQL ${PG_MAJOR} provisioned."
echo "listen_addresses=127.0.0.1"
echo "database=${DB_NAME}"
echo "role=${DB_USER}"
ss -ltn | grep -E '127\.0\.0\.1:5432\b' >/dev/null
runuser -u postgres -- psql -d "${DB_NAME}" -tAc "SELECT current_setting('server_version'), current_database();"
