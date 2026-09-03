# Tab completion for the cmdbsyncer CLI, sourced by /etc/profile.
#
# Click builds the completion function by running the CLI itself, which
# takes about a second. That is fine once per container, so the generated
# source is cached and only rebuilt when the cache is gone. Only bash can
# use it — busybox ash has no programmable completion, so it stays out of
# the way there.

_cmdbsyncer_load_completion() {
    [ -n "$BASH_VERSION" ] || return 0

    cli=$(command -v cmdbsyncer 2>/dev/null) || cli=/srv/cmdbsyncer
    [ -x "$cli" ] || return 0

    cache="${TMPDIR:-/tmp}/.cmdbsyncer-completion.bash"
    # The cache is sourced, so every line in it is executed. Only accept
    # it if it really is Click's generated script: should the CLI ever
    # print anything else on stdout, caching it blindly would run that
    # as a shell command on every login, and the stale file would keep
    # doing so until someone deleted it by hand.
    # Checking the *first* line, not just any line: a stray line ahead of
    # an otherwise intact script is exactly the case worth catching.
    _cmdbsyncer_cache_ok() {
        [ -s "$1" ] && head -n 1 "$1" 2>/dev/null \
            | grep -q '^_cmdbsyncer_completion()'
    }
    if ! _cmdbsyncer_cache_ok "$cache"; then
        _CMDBSYNCER_COMPLETE=bash_source "$cli" > "$cache.new" 2>/dev/null
        if _cmdbsyncer_cache_ok "$cache.new"; then
            mv "$cache.new" "$cache"
        else
            rm -f "$cache.new" "$cache"
        fi
    fi
    unset -f _cmdbsyncer_cache_ok
    if [ -s "$cache" ]; then
        . "$cache"
        # Click registers the completion under the bare command name.
        # In the container the CLI is called as ./cmdbsyncer from /srv,
        # so register that spelling too instead of relying on bash's
        # fallback from a path to its basename.
        complete -o nosort -F _cmdbsyncer_completion ./cmdbsyncer 2>/dev/null
    fi
}

_cmdbsyncer_load_completion
unset -f _cmdbsyncer_load_completion
unset cli cache
