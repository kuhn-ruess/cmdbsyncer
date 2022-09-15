# Ansible
Playbooks which are used for the CMDB Syncer automation

## Features
 - Agent Installation, TLS and Bakery configuration for Windows and Linux

## Problems and Fixes

### Distributed Monitoring, Agent Download from API
Set Reverse Proxy in Apache:
```
SSLProxyEngine On
SSLProxyCheckPeerCN off
RewriteEngine On
RewriteRules /sitename/check_mk/api/1.0/domain-types/agent/(.*)$ https://mastersite/sitename/check_mk/api/1.0/domain-types/$1 [P]
```
