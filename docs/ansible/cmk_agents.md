# General
The cmk_agent_mngmt.yml Playbook contains everything to mange the Installation and the Bakery and TLS Registrations of you Checkmk Agents. This works for Linux and Windows.

## Extra Information
Ansible needs some Information more, it needs to know on which Checkmk Server the Host is running, or if it is even necessary to do a certain operation like installing an Agent, or do some kind of Registration. For that, the Syncer uses an Inventory Feature. It queries checkmk and asks for all Information the Syncer needs to know. This should run as Cronjob. The Command is:
`./cmdbsyncer checkmk hosts_inventory account`. 

After the run, you can verify what the Inventory found, when you check a Host in the Frontend and Scroll to inventory:

![](img/inventory.png)

## Ansible Variables
Next, you need to seed Variables and Conditions. This is nesseary in order to know when a Action is due, or what Credentials are used.

The following Variables existing in the Ansible Role. You learn later how to set them:

| Variable | Description |
| :--------|:------------|
| cmk_user | User for Auth in Checkmk and API Operations |
| cmk_password | Password to the user |
| cmk_server | The Site specifc Server for Registrations (Distributed Monitoring) |
| cmk_main_site | Master Site |
| cmk_main_server | Master Sites Address (with https://) |
| cmk_install_agent | True if Agent has to be installed |
| cmk_register_tls | True if TLS Registration has to be done |
| cmk_register_bakery | True if Bakery Registration as to be done |
| cmk_delete_manual_files | Set True if you delte the Checkmk Files on the Server |
| cmk_linux_tmp | Temp dir which is used on Linux |
| cmk_agent_receiver_port | Port for Agent TLS Registration |
| cmk_discovery | Trigger Checkmk Discovery on Host |
| cmk_windows_tmp | Temo dir on Windows Server|

As shortcut, you can install a default set of rules with:

```
./cmdbsyncer ansible seed_cmk_default_rules
```

## Configuration

### Syncer Settings

You can set which Hosts you want to manage via Ansible, or deploy custom Variables to some Hosts with the Ansible Rules.


 To set the Credentials, Ansible should use contact Checkmk, see here:
![](img/credentials.png)

Example how to Install the Agent when a given Service Output was found:
![](img/install_agent.png)

Likewise, you can configure if to register to bakery or the TLS. Filter for example for the TLS Error message in the Service Output (See the seed_cmk_default_rules to have more exmpales directly in your system)

## Debug
Before you run anything in Ansible, use the debug_host feature to check if the Outcome is what you want:
`./cmdbsyncer ansible debug_host HOSTNAME`
The command will tell you all variable outcomes you will have in Ansible.

