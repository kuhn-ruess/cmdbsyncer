# APP Configuration

The application comes with some default Settings, for example to set the URL prefix or MongoDB Connection. The setting of this is important, if some links in the Backend won't work.
All what's set, you will find in _application/config.py_, but you should not change something in this file.
Instead, just create a file _local_config.py_ in the root folder. It has to contain at least a dictionary called config. With the Keys of this Dictionary, you can overwrite every key from application/config.py, or you can add all settings the Framework Flask has.
It's even possible to change the logging behaviour. See this Example who does that:

```
"""
Local Config
"""
import logging

config = {
    'LOG_LEVEL' : logging.DEBUG,
    'LOG_CHANNEL' : logging.StreamHandler(),
    'BASE_PREFIX' : '/cmdbsyncer/'
}
```

