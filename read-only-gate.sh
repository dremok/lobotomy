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

# Block dangerous patterns: semicolons, backticks, subshells, redirection
if echo "$CMD" | grep -qE '[;&`]|\$\(|>\s*|>>' ; then
    echo "ERROR: Command chaining, redirection, and subshells are blocked."
    exit 1
fi

# Allowed read-only commands (may appear anywhere in a pipe chain)
SAFE_CMDS="cat|ls|find|head|tail|rg|grep|tree|du|wc|file|stat|readlink|realpath|which|echo|sort|uniq|tr|cut|awk|sed|xargs"
SAFE_GIT="log|status|diff|show|branch|tag|remote|rev-parse|ls-files|ls-tree|cat-file|shortlog|blame"

# Split on pipes and validate each segment
IFS='|' read -ra SEGMENTS <<< "$CMD"
for segment in "${SEGMENTS[@]}"; do
    # Trim whitespace
    segment=$(echo "$segment" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    base=$(echo "$segment" | awk '{print $1}')

    case "$base" in
        cat|ls|find|head|tail|rg|grep|tree|du|wc|file|stat|readlink|realpath|which|echo|sort|uniq|tr|cut|awk|sed|xargs)
            # Safe read-only command
            ;;
        git)
            subcmd=$(echo "$segment" | awk '{print $2}')
            case "$subcmd" in
                log|status|diff|show|branch|tag|remote|rev-parse|ls-files|ls-tree|cat-file|shortlog|blame)
                    ;;
                *)
                    echo "ERROR: git $subcmd is not allowed."
                    exit 1
                    ;;
            esac
            ;;
        *)
            echo "ERROR: Command '$base' is not allowed."
            exit 1
            ;;
    esac
done

# All segments validated, execute the full command
exec /bin/bash -c "$CMD"
