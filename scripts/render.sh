#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
ROOT=$(cd "$(dirname "$0")/.." && pwd)
# training renders fewer star captchas: the star variant saturates early (docs/data_protocol_v3.md, deviation 2)
case ${1:-} in
  train | train_amb) SEED=3001 STAR=0.2 ;;
  val | val_sub | val_amb) SEED=3002 STAR=0.5 ;;
  test) SEED=3003 STAR=0.5 ;;
  *) echo "usage: render.sh train|train_amb|val|val_sub|val_amb|test" >&2; exit 1 ;;
esac
OUT=$ROOT/data/rendered/$1
export PROCS=4 LOGDIR=$OUT/_logs
mkdir -p "$LOGDIR"
"$ROOT/harness/run.sh" render --sdf "$ROOT"/data/pubchem/sdf/*.sdf.gz --cids "$ROOT/data/split/$1.txt" --out "$OUT" \
  --seed $SEED --star-ratio $STAR --prefix "$1" --threads 6
