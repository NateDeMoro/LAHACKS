#!/usr/bin/env bash
# Start the three agents in the background (logs in logs/agents/). Stop with: pkill -f "python -m agent\."
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs/agents
for m in main intake_agent evidence_agent; do
  nohup uv run --group agent --env-file .env python -m agent.$m > logs/agents/$m.log 2>&1 &
done
echo "agents starting; then run: uv run --group agent --env-file .env python scripts/connect_agents.py"
