#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
CLASSPATH=$HERE/build/harness.jar:$(ls "$HERE"/lib/*.jar | tr '\n' ':')
PROCS=${PROCS:-1}
if [[ ${1:-} != render || $PROCS == 1 ]]; then
  exec java ${JAVA_OPTS:--Xmx16g} -cp "$CLASSPATH" noauthbot.harness.Main "$@"
fi

LOGDIR=${LOGDIR:-$(mktemp -d)}
part_pids=()
for ((part = 0; part < PROCS; part++)); do
  java ${JAVA_OPTS:--Xmx3g -XX:ParallelGCThreads=2 -XX:CICompilerCount=2} -cp "$CLASSPATH" noauthbot.harness.Main "$@" \
    --part "$part/$PROCS" > "$LOGDIR/part$part.log" 2>&1 &
  part_pids+=($!)
  if ((part == 0)); then
    # JVMs starting together race on unpacking the Skija native library
    for _ in $(seq 150); do compgen -G "/tmp/skija_*/libskija.so" > /dev/null && break; sleep 0.2; done
    sleep 2
  fi
done

status=0
for pid in "${part_pids[@]}"; do wait "$pid" || status=1; done
cat "$LOGDIR"/part*.log
exit $status
