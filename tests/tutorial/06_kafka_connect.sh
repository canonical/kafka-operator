#!/bin/bash
# Extracted from : docs/tutorial/use-kafka-connect.md
# Regenerate with: python3 tests/tutorial/extract_commands.py docs/tutorial/use-kafka-connect.md <output.sh>
#
# To skip a block in the Markdown source, add this comment on the line
# immediately before its opening fence (blank lines are fine between them):
#   <!-- test:skip -->
#
# Only ```shell fences are extracted; use any other tag to naturally exclude a block.

set -euo pipefail

# shellcheck source=tests/tutorial/helpers.sh
. "$SPREAD_PATH/tests/tutorial/helpers.sh"

juju status

sudo tee -a /etc/sysctl.conf > /dev/null <<EOT
vm.max_map_count=262144
vm.swappiness=0
net.ipv4.tcp_retries2=5
fs.file-max=1048576
EOT

sudo sysctl -p

cat <<EOF > ~/cloudinit-userdata.yaml
cloudinit-userdata: |
  postruncmd:
    - [ 'echo', 'vm.max_map_count=262144', '>>', '/etc/sysctl.conf' ]
    - [ 'echo', 'vm.swappiness=0', '>>', '/etc/sysctl.conf' ]
    - [ 'echo', 'net.ipv4.tcp_retries2=5', '>>', '/etc/sysctl.conf' ]
    - [ 'echo', 'fs.file-max=1048576', '>>', '/etc/sysctl.conf' ]
    - [ 'sysctl', '-p' ]
EOF

juju model-config --file=~/cloudinit-userdata.yaml

juju deploy kafka-connect --channel edge
juju deploy postgresql --channel 14/stable
juju deploy opensearch --channel 2/stable --config profile=testing

juju_wait --timeout 1200 --allow-blocked opensearch,kafka-connect

juju integrate opensearch self-signed-certificates

juju integrate kafka kafka-connect

juju integrate kafka-connect self-signed-certificates

juju_wait --timeout 1200

cat <<EOF > ~/populate.sql
CREATE TABLE posts (
  id serial not null primary key,
  content text not null,
  likes int default null,
  created_at timestamp with time zone not null default now()
);

INSERT INTO posts (content, likes) 
VALUES 
  (
    'Charmed Apache Kafka is an open-source operator that makes it easier to manage Apache Kafka, with built-in support for enterprise features.', 
    150
  ), 
  (
    'Apache Kafka is a free, open-source software project by the Apache Software Foundation. Users can find out more at the Apache Kafka project page.', 
    200
  ), 
  (
    'Charmed Apache Kafka is built on top of Juju and reliably simplifies the deployment, scaling, design, and management of Apache Kafka in production', 
    100
  ), 
  (
    'Charmed Apache Kafka is a solution designed and developed to help ops teams and administrators automate Apache Kafka operations from Day 0 to Day 2, across multiple cloud environments and platforms.', 
    1000
  ), 
  (
    'Charmed Apache Kafka is developed and supported by Canonical, as part of its commitment to provide open-source, self-driving solutions, seamlessly integrated using the Operator Framework Juju. Please refer to Charmhub, for more charmed operators that can be integrated by Juju.', 
    60
  );
EOF

juju scp ~/populate.sql postgresql/0:/home/ubuntu/populate.sql

juju run postgresql/leader get-password

_CMD_OUTPUT=$(juju run postgresql/leader get-password)
PG_PASSWORD=$(echo "$_CMD_OUTPUT" | grep 'password:' | awk '{print $2}')

juju ssh postgresql/leader "PGPASSWORD=${PG_PASSWORD} psql --host \$(hostname -i) --username operator --dbname postgres -c 'CREATE DATABASE tutorial'"
juju ssh postgresql/leader "cat /home/ubuntu/populate.sql | PGPASSWORD=${PG_PASSWORD} psql --host \$(hostname -i) --username operator --dbname tutorial"
juju ssh postgresql/leader "PGPASSWORD=${PG_PASSWORD} psql --host \$(hostname -i) --username operator --dbname tutorial -c 'SELECT COUNT(*) FROM posts'"

juju deploy postgresql-connect-integrator \
    --channel edge \
    --config mode=source \
    --config db_name=tutorial \
    --config topic_prefix=etl_

juju integrate postgresql-connect-integrator postgresql
juju integrate postgresql-connect-integrator kafka-connect

juju_wait --timeout 1200

juju deploy opensearch-connect-integrator \
    --channel edge \
    --config mode=sink \
    --config topics="etl_posts"

juju integrate opensearch-connect-integrator opensearch
juju integrate opensearch-connect-integrator kafka-connect

juju_wait --timeout 1200

_CMD_OUTPUT=$(juju run opensearch/leader get-password --wait=5m)
OS_PASSWORD=$(echo "$_CMD_OUTPUT" | grep 'password:' | awk '{print $2}')

OPENSEARCH_IP=$(juju ssh opensearch/0 'hostname -i' | tr -d '\r\n')

sleep 30

curl -u admin:${OS_PASSWORD} -k -sS "https://${OPENSEARCH_IP}:9200/etl_posts/_search?pretty=true"

juju ssh postgresql/leader "PGPASSWORD=${PG_PASSWORD} psql --host \$(hostname -i) --username operator --dbname tutorial -c \"INSERT INTO posts (content, likes) VALUES ('my new post', 1)\""

sleep 30

curl -u admin:${OS_PASSWORD} -k -sS "https://${OPENSEARCH_IP}:9200/etl_posts/_search?pretty=true"
