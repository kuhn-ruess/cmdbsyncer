# How it all works

The CMDB Syncer [imports](import.md) all sort of devices as Hosts into his Database. Along with the Hostnames, [Labels and Inventory](host_labels_inventory.md) will store as attributes. That could be an IP-Address, a Contact or every other type of Data, which fit in a key value pair.

With rules, you can then [add additional Attributes](custom_attributes.md) and [Rewrite](rewrite_attributes.md) existing ones. The goal is to use this Attributes as Condition, to control the Process of [export](export.md) to another system.

The Functions of the Export depend on the Other System. You will find the Details on the Module Section.

When a Host is no longer found on an import source, it will be deleted after a grace time. Hosts no longer in this Database, will also be deleted on the export target.


With the Command Line Interface of the Syncer, you can debug all Outcomes before you start the Sync.

## Architecture

The System is Module-based. It supports [Plugins](../advanced/own_plugins.md) to import and export, wich can use a simple API, but also ships well tested internal plugins who cover a lot.

The Application is written in Python, the Local Database is a MongoDB. [Docker](setup_docker.md) is also fully supported to run it.

The Admin Interface uses Flask-Admin. This simplifies a lot, but also limits some things in the frontend.