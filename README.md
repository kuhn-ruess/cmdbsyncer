# Sync System for Hosts to other Systems and APIs like Checkmk

Rule Based and Modular System to sync Hosts into Checkmk.
Main Goal is the complete Organization of the Hosts based on CMDB Systems

## Main Functions
- Web Interface with Login, 2FA and User management
- All configuration besides Installation in Web Interface (with User Roles)
- Rules to control the Synchronization:
  - Based on Hostname Patterns
  - Based on Labels
  - Outcome is Rewrite Labels, add Custom Labels, Ignore Hosts, Move to Folder and more
- Automatically Creates the folder in Checkmk and Moves the Hosts (cmkv2)
- Automatically Deletes Hosts if needed
  - Management of the complete Host lifetime in Checkmk
- Simple Plugin API to integrate own Data Sources, or even own Targets (Target must not be Checkmk, also Checkmk can be the source instead of a CMDB).
- Integrated options to prevent to many Updates in Checkmk (e.g. Updates only on Label Change). For Rule changes, the Update can be forced.

Main Focus is Checkmk 1.x and Checkmk 2.x, but in theory it will work with all systems.

For a quick test, best use Docker Compose. All regarding Documentation can be found in the [WIKI](https://github.com/Bastian-Kuhn/cmdb-syncer/wiki)

To use with Apache and uWSGI, see Wiki. This Setup can be used on your Checkmk Server.
