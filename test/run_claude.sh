#!/bin/bash
# Score all 5,400 versions with a Claude model through `claude -p` (Claude subscription).
#   bash test/run_claude.sh haiku-5-5-high
# call_llm.py pauses at THRESHOLD % of a quota window and continues after the reset, so this can be left running.
# Re-running resumes; versions that failed are retried on the next pass.
cd "$(dirname "$0")/.."
MODEL=${1:-haiku-5-5-high}
THRESHOLD=${THRESHOLD:-90}
WORKERS=${WORKERS:-10}
for pass in $(seq 1 5); do
    caffeinate -i python3 test/call_llm.py --model "$MODEL" --workers "$WORKERS" --threshold "$THRESHOLD"
    python3 test/call_llm.py --model "$MODEL" --status | grep -q " 0 left" && break
done
python3 test/call_llm.py --model "$MODEL" --status
