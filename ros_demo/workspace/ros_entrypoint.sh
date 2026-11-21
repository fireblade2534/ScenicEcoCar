#!/bin/bash
set -eo pipefail

source /usr/local/bin/base_entrypoint.sh

echo "=== Building application workspace ==="
if [ -d /workspace/src ]; then
    cd /workspace
    colcon build

    source /workspace/install/setup.bash
fi

cd /workspace

echo "=== ROS 2 environment ready ==="
exec "$@"
