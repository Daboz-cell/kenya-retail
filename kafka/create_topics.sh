#!/usr/bin/env bash
set -euo pipefail

TOPICS=("retail.pos.sales:3" "retail.inventory.movements:3" "retail.stock.alerts:1" "retail.dead_letter:1")
KT="/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092"

for entry in "${TOPICS[@]}"; do
  name="${entry%%:*}"
  partitions="${entry##*:}"
  docker exec kr_kafka $KT --create --if-not-exists \
    --topic "$name" --partitions "$partitions" --replication-factor 1 \
    --config retention.ms=604800000
done

docker exec kr_kafka $KT --describe
