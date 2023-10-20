# Rewrite Hostnames

The renaming of Hostnames must happen on import. For most of the integrated plugins, you can do that using the Jinja2 Template language. This works since version 3.4. For that, an Account has to be set for your import. If you save that account, a Custom Attribute 'rewrite_hostname' will appear.

## Example
Would the host have an Attribute dns, a rewrite could look like this:

<pre>
{{HOSTNAME}}.{{dns}}
</pre>

![](img/rewrite_hostname.png)


Note that HOSTNAME is the internal variable for the current hostname, and dns can the exact name of the attribute the has.

If you change that setting later, make sure to remove the hosts with the not longer matching hostnames. Because for Syncer, a Host after rewrite will be a completely new object.

