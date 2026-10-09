#!/bin/sh
# Link private documentation without copying it into public source control.
set -eu

if [ "$#" -ne 1 ]; then
    printf '%s\n' 'Usage: ./load-context.sh /absolute/path/to/private/context/directory' >&2
    exit 2
fi

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
context_dir=$(CDPATH= cd -- "$1" && pwd -P)

# Preflight both files before creating either link.
for name in PROJECT_CONTEXT.md TRELLO_WORKFLOW.md; do
    source_file="$context_dir/$name"
    target_file="$repo_dir/$name"
    if [ ! -f "$source_file" ]; then
        printf 'Missing context file: %s\n' "$source_file" >&2
        exit 1
    fi
    if [ -e "$target_file" ] || [ -L "$target_file" ]; then
        if [ ! -L "$target_file" ] || [ "$(readlink "$target_file")" != "$source_file" ]; then
            printf 'Refusing to replace: %s\n' "$target_file" >&2
            exit 1
        fi
    fi
done

for name in PROJECT_CONTEXT.md TRELLO_WORKFLOW.md; do
    if [ ! -L "$repo_dir/$name" ]; then
        ln -s "$context_dir/$name" "$repo_dir/$name"
    fi
done
printf '%s\n' 'Private project context and board conventions linked.'
