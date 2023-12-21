
For your Plugins, please only import from syncerapi.v1
Otherwise, we can't guarantee that updates won't break something in your scripts.

Example:

```
 from syncerapi.v1 import Host
```

The Api Includes:

- Host
- get_account
- register_cronjob
- cc (Color Codes)

# Host Object API
::: application.models.host.Host

# Debug API
::: application.modules.debug
