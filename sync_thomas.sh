#!/bin/bash
cd /home/thomakal/apps/healthy
env $(cat thomas/.env | grep -v '^#' | xargs) python3 garmin_collector.py --days 3 >> thomas/sync.log 2>&1
env $(cat thomas/.env | grep -v '^#' | xargs) python3 yazio_connector.py --gays 3 >> thomas/sync.log 2>&1
