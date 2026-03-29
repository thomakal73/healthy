#!/bin/bash
cd /home/thomakal/apps/healthy
env $(cat thomas/.env | grep -v '^#' | xargs) python3 advisor_backend.py