# Ansible Integration
The CMDB Syncer can be used, to deploy Checkmk Agents, register them to Checkmk for TLS and for the Bakery.


## Installation

You can either use the Ansible subfolder of this Project directly on the server where the Syncer is installed,
or use it remotely. In this second case, the syncers Rest API is used as Data source.

## Local Installation
- Change into the CMDB Syncer Directory
- Load his environment (source ENV/bin/activate)
- One Time: Install the additional Requirements: pip install -r ./ansible/requirements.txt
- Change to the ansible subdir: cd ./ansible
-  You are Ready

## Remote Installation
- [Checkout the Repo](../basics/checkout_code.md)
- Copy the Inventory File: cp cmdbsyncer_inventory_rest local_cmdbsyncer_inventory_rest
- Edit the File and set the URL (beware of Proxy) to the Syncer Installation, and set a Secret:
- ![](img/secret.png)

- The Secret is set up in the Account:
- ![](img/account.png)
- You are Ready

## Required Information
Ansible needs some Information more, it needs to know on which Checkmk Server the Host is running, or if it is even necessary to do a certain operation like installing an Agent, or do some kind of Registration. For that, the Syncer uses an Inventory Feature. It's basically queries checkmk and asks for all Information the Syncer needs to know. This should run as Cronjob. The Command is:
`./cmdbsyncer checkmk hosts_inventory account`. 

After the run, you can verify what the Inventory found, when you check a Host in the Frontend and Scroll to inventory:

![](img/inventory.png)

## Ansible Variables

The following Variables are used from the Ansible Role. You learn later how to set them:
- cmk_user
- cmk_password
- cmk_server
- cmk_install_agent
- cmk_register_tls
- cmk_register_bakery
- cmk_delete_manual_files
- cmk_linux_tmp
- cmk_agent_receiver_port
- cmk_discovery
- cmk_windows_tmp (Needed for Windows Agent only)
- cmk_main_site (Because of possible distributed Monitoring)
- cmk_main_server

# Using

## Syncer Settings

You can set which Hosts you want to manage via Ansible, or deploy custom Variables to some Hosts with the Ansible Rules.

## Set the Credentials Ansible should use contact Checkmk:
![](img/credentials.png)

## Install the Agent when a given Service Output was found:
![](img/install_agent.png)

Likewise, you can configure if to register to bakery or the TLS. Filter for example for the TLS Error message in the Service Output

#Ansible
Before you run anything in Ansible, use the debug_host feature to check if the Outcome is what you want:
`./cmdbsyncer ansible debug_host HOSTNAME`
The command will tell you all variable outcomes you will have in Ansible.

## Run Ansible
The only difference between a local CMDB Syncer installation and a remote one is the inventory source.
Change into the ansible dir, make sure you have the environment loaded.
And now you can run Ansible:
`ansible-playbook -i INVENTORY_SOURCE --limit somehost cmdbsyncer_agent_mngmt.yml`
The Inventory source is either the rest plugin you have copied and adapted,
or [cmdbsyncer_inventory](https://github.com/Bastian-Kuhn/cmdb-syncer/blob/main/ansible/cmdbsyncer_inventory)
or [cmdbsyncer_inventory_docker](https://github.com/Bastian-Kuhn/cmdb-syncer/blob/main/ansible/cmdbsyncer_inventory_docker)
All of them just returning the Information from the cmdb syncer formatted as an Ansible compatible inventory
