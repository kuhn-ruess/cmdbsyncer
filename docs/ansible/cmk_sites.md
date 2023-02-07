# Checkmk Site Managament

The Included Playbook cmk_server_mngmnt.yml makes use of the following functions:

- Installation of Checkmk Versions
- Creation of Checkmk Sites
- Updates of Checkmk Sites

To do so, configure your Checkmk Target Version, and your Checkmk Sites inside the Syncer. 
You need to place the Checkmk Installation Package under /tmp. If not, the playbook will try to download it, using the supplied credentials. Then it's transfered to you remote server. That means this servers do not need an internet connection.

As a current limit, the System can only manage one Checkmk Site per Server. 

The Configuration can be Found in Rules-> Checkmk

## CMK Server Settings
| Option | Description |
|:-------|:------------|
| Name | Name of config set |
| Server User | User for Ansible to connect to the Server. Sudo needs to be possibe |
| CMK Version | Versions String like 2.1.0p19 |
| CMK Edition | Enterprise or RAW |
|CMK Version Filename | Filename like found on the cmk download server, example: check-mk-enterprise-2.1.0p19_0.bullseye_amd64.deb |
| Inital Password | This password will be set for new sites |
|Subscription Username/ Password | Your Checkmk Subscription Account |

## CMK Sever Sites

| Option | Description |
|:-------|:------------|
| name | Site Name |
| Server Address | Address of Server for SSH (without protocoll) |
| Settings Master | Select the CMK Server Settings Entry |
