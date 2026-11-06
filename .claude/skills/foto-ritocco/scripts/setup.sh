#!/bin/sh
# Create the skill's private Python environment. Safe to run again.
set -e
V="$HOME/.cache/foto-ritocco/venv"
[ -x "$V/bin/python" ] || python3 -m venv "$V"
"$V/bin/python" -m pip install --quiet --upgrade pip
"$V/bin/python" -m pip install --quiet numpy pillow opencv-python-headless onnxruntime-openvino
"$V/bin/python" -c "import cv2, onnxruntime as o; print('cv2', cv2.__version__, '| onnxruntime', o.__version__, o.get_available_providers())"
