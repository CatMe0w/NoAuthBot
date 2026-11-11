#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$ROOT/data/labels
mkdir -p "$OUT"
"$ROOT/harness/run.sh" labels --sdf "$ROOT"/data/pubchem/sdf/*.sdf.gz --out "$OUT" --threads 12 \
  2>&1 | tee -a "$OUT/labels.log"
