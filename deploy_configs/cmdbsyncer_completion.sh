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
    if [ ! -s "$cache" ]; then
        _CMDBSYNCER_COMPLETE=bash_source "$cli" > "$cache" 2>/dev/null
    fi
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
