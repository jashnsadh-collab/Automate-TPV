#!/bin/bash
cd "$(dirname "$0")"
python3 tpv_agent.py --predict 30 2>&1 | tee "output/daily_$(date +%Y-%m-%d).log"
