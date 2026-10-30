#!/bin/bash
# Score all 5,400 versions with a GPT model (high effort) through test/codex_proxy.py (ChatGPT subscription).
#   bash test/run_gpt.sh                      # gpt-6.1-sol
#   bash test/run_gpt.sh gpt-6.1-terra
# The proxy pauses at THRESHOLD % of a quota window and continues after the reset, so this can be left running.
# Re-running resumes; versions that failed are retried on the next pass.
cd "$(dirname "$0")/.."
PORT=${PORT:-8200}
THRESHOLD=${THRESHOLD:-95}
WORKERS=${WORKERS:-6}
MODEL_ID=${1:-gpt-6.1-sol}
MODEL=$MODEL_ID-high
mkdir -p test/logs

# Never reuse a proxy left on this port by an earlier run: its settings may differ.
pkill -f "codex_proxy.py --port $PORT " ; sleep 1
nohup python3 -W ignore test/codex_proxy.py --port "$PORT" --model "$MODEL_ID" --effort high --threshold "$THRESHOLD" \
    >> test/logs/codex_proxy.out 2>&1 < /dev/null &
for _ in $(seq 30); do sleep 2; curl -sf "http://localhost:$PORT/v1/models" > /dev/null && break; done
curl -sf "http://localhost:$PORT/v1/models" > /dev/null || { echo "proxy did not start, see test/logs/codex_proxy.out"; exit 1; }

for pass in $(seq 1 5); do
    caffeinate -i python3 test/call_llm.py --model "$MODEL" --workers "$WORKERS" --threshold "$THRESHOLD" \
        --proxy-url "http://localhost:$PORT/v1"
    python3 test/call_llm.py --model "$MODEL" --status | grep -q " 0 left" && break
done
python3 test/call_llm.py --model "$MODEL" --status
