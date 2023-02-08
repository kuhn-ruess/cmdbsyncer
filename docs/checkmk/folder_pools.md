# Folder Pools

A Folder Pool is used if you want to import a high number of Hosts into Checkmk, but automatically spread them over your Sites. This is archived when you define Folder Pools in Checkmk→Folder Pools, and define the Number of total Seats. A Seat is a Place in this Folder. The Folders will be created in Checkmk and you just need to link them to your remote sites. In the CMDB Syncer, you then need to define an CMK Export Rule which match for the Hosts you want. Please note that Folder pools will be added to the normal Folder hierarchies, if multiple Rules match. You can prevent that using the Last Match option for Rules.

CMK Syncer will also automatically free the seat in the pool if you ignore the hosts, or nor folder_pool Rule matches any more.

You can set them up in:
**Rules → Checkmk → Folder Pools**
