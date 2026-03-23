#!/bin/bash
# read-only-gate.sh — SSH forced command for the lobotomy user.
# Allows read-only commands to Max's filesystem, blocks writes/deletes.
# Deployed to /Users/lobotomy/read-only-gate.sh on the laptop.
#
# Usage in authorized_keys:
#   command="/Users/lobotomy/read-only-gate.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding ssh-ed25519 AAAA...

set -euo pipefail

CMD="${SSH_ORIGINAL_COMMAND:-}"

if [ -z "$CMD" ]; then
    echo "ERROR: No command provided. Interactive shells are not allowed."
    exit 1
fi

# Block command chaining and injection
if echo "$CMD" | grep -qE '[;|&`]|\$\(|>\s|>>' ; then
    echo "ERROR: Command chaining, redirection, and subshells are blocked."
    exit 1
fi

# Writable sandbox paths (lobotomy user can write here)
SANDBOX="/Users/lobotomy/sandbox"
TEST_RUNS="/Users/lobotomy/test-runs"
SNAPSHOTS="/Users/lobotomy/snapshots"

# Extract the base command (first word)
BASE_CMD=$(echo "$CMD" | awk '{print $1}')

# Read-only commands: always allowed
case "$BASE_CMD" in
    cat|ls|find|head|tail|rg|grep|tree|du|wc|file|stat|readlink|realpath|which|echo)
        exec /bin/bash -c "$CMD"
        ;;
    git)
        # Only allow read-only git subcommands
        SUBCMD=$(echo "$CMD" | awk '{print $2}')
        case "$SUBCMD" in
            log|status|diff|show|branch|tag|remote|rev-parse|ls-files|ls-tree|cat-file|shortlog|blame)
                exec /bin/bash -c "$CMD"
                ;;
            *)
                echo "ERROR: git $SUBCMD is not allowed. Read-only git commands only."
                exit 1
                ;;
        esac
        ;;
    # Write commands: only allowed to sandbox paths
    cp|mkdir|tee)
        if echo "$CMD" | grep -qE "(${SANDBOX}|${TEST_RUNS}|${SNAPSHOTS})" ; then
            exec /bin/bash -c "$CMD"
        else
            echo "ERROR: Write operations only allowed to /Users/lobotomy/{sandbox,test-runs,snapshots}."
            exit 1
        fi
        ;;
    *)
        echo "ERROR: Command '$BASE_CMD' is not allowed."
        exit 1
        ;;
esac
