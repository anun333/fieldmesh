#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Run one of these scripts in the Timestral container: four threads on CPUS (4-7 unless
# set), 6 GB, no network unless FETCH=1 (the first run, to download the weights to HF_DIR).
#   ./run.sh DATA_DIR OUT_DIR HF_DIR script.py [args...]
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
DATA=$(cd "$1" && pwd); OUT=$(cd "$2" && pwd); HF=$(cd "$3" && pwd); shift 3
NET="--network none"; OFFLINE=1
[ "${FETCH:-0}" = 1 ] && NET="" && OFFLINE=0
exec docker run --rm $NET --cpus 4 --cpuset-cpus "${CPUS:-4-7}" --memory 6g \
  -e HF_HOME=/hf -e HF_HUB_OFFLINE=$OFFLINE -e OMP_NUM_THREADS=4 -e MKL_NUM_THREADS=4 \
  -v "$DATA":/data:ro -v "$HERE":/scripts:ro -v "$OUT":/out -v "$HF":/hf \
  fieldmesh-timestral python "/scripts/$@"
