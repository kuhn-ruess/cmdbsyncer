## set_export_problem(message)
Mark the host if you encounter a problem when trying to export it.

## lock_to_folder(folder_name)
Internal Function for Folder Pool. Assigns the Folder to the host.
To remove, set folder_name to False. 
Note that the Folder Seat will still be taken. Use

```
from application.helpers import poolfolder
poolfolder.remove_seat(folder_name)
```
to remove the actual seat.
## get_folder()
Returns the Folder if the host is locked to one.
## replace_label(key, value)
Update a single Label by Key inside our DB.
## set_labels(label_dict)
Overwrite all labels in our DB.
## get_labels()
Get dict of all current labels stored in DB.
## add_log(entry)
Add a History entry to the log. Can be seen in the Admin Panel
## set_account(account_id, account_name)
Add the Account to the Hosts. This is necessary that the Syncer only touches Hosts coming from him.
It will raise an Exception if the Hosts already belongs to another Account.
## def set_import_sync()
Mark if the Import did a sync to this host.
This is useful if the sync takes more time, and you don't want to sync every time the import run.
## def set_import_seen()
Use this always if the System is found with your import. This helps the maintenance jobs.
A solution if your source only shows Updates will come soon. 
## def set_source_not_found()
Mark the Host no longer Active. So, he will be removed e.g. from Checkmk and after the grace time you set for the maintenance job, also from our db. 
## def set_export_sync()
Mark that you have Updated the Host on your target. Not relevant for import.
## def need_import_sync(hours=24)
Counterpart for set_import_sync(). Pass after how many hours you want to sync the Host Details again.
## def need_update(hours=24*7)
Counterpart for set_target_update(), can be used to force updates after time. Also, the force_update function from the Backend is passed here.
It is not needed for the CMK export, since there the labels are compared. 
