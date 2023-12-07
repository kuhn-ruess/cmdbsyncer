# CMDB Syncer

Rule Based and Modular System to syncronize Hosts into and between Checkmk, Netbox and other Systems.
Main Goal is the complete Organization of the Hosts based on CMDB Systems


![Rules](https://user-images.githubusercontent.com/899110/201333967-2d7f3f35-cc69-4cad-931f-1da096f94056.png)
![Debug Options](https://user-images.githubusercontent.com/899110/201333725-d699d50f-a5eb-4539-a3af-3db3e0647ebb.png)

## Quickstart
I recommend docker-compose:
- checkout the Repo
- run ./helper up
- run ./helper create_user 'mail@address.org' (to create login)
- Login to the Interface: http://your-host:5003
This is runs a Development Version which you can use to test everthing

## Main Functions
- Web Interface with Login, 2FA and User management
- All configuration besides Installation in Web Interface
- Simple Plugin API to integrate own Data Sources
- Various Debug Options with the ./cmdbsyncer command
- Rules to control the Synchronization:
  - Based on Host Attributes
  - Attribute Rewrites
  - Filters
  - Action Rules

## Modules
### Checkmk
- Manges full Host Lifecycle (creation, labels, folders, deletion)
- Sync and Update all possible Host Attributes
- Full management of Checkmk Folders
 or even own Targets (Target must not be Checkmk, also Checkmk can be the source instead of a CMDB).
- Folder Pool Feature to split big amounts of Hosts automatticly between folders (and therfore sites).
- Creation of Host-, Contact- and Service Groups
- Creation of all types of Checkmk Rules
- Creation of BI Rules
- Creation of Tags
- Management of Checkmk (Fallback) users (Create/ Delete/ Reset Password/ Disable Login)
- Integrated options to prevent to many Updates in Checkmk
- Command to Active Configuration
- Command to Bake and Sign Agents
- Inventory for Host Attributes (need e.g. for Ansible, like on which site is server on)

### Ansible
- Rule Based Inventory Source
- All Functions for Checkmk Agent Management (Installation, TLS Registration, Bakery Registration)
- Linux and Windows

### Netbox
- Rulebased Export and Import Devices to Netbox

### Cisco DNA
- Import devices and their Interface Information

### CSV
- Manage Hosts based on CSV File (Import Source)
- Add Addional Informationen from CSV Files to your Hosts (eg. Overwrite IP Addresses)

### MSSQL
- Import

### MySQL
- Import

### LDAP
- Import

### Rest APIs/ Json Files
- Import

## Other
- [Documentation](https://cmdbsyncer.readthedocs.io/en/latest/)
