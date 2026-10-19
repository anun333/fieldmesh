# SPDX-License-Identifier: Apache-2.0
# The Timestral package (Apache-2.0) and CPU PyTorch, apart from the farm's own software.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir "git+https://github.com/mistralai/timestral.git" numpy
RUN useradd -m -u 1000 runner
USER runner
WORKDIR /work
