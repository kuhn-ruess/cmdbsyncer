# Caching
Specially if you have servals thousands of hosts, it makes a difference if a process per host takes 1 Second or just a few Millie Seconds. So to speed Syncer processes up, you can enable "USE_CACHE". This will cache then most of the Calculations automatically, until the Cache is deleted. 
The Cache will automatically delete for a Host if the Import updates his Labels.  If you, of course Change Rules, you need to delete this cache. 
For that, you will find a "Commit Changes" link in the Panel corner. 

From the Command line, you can call _./cmdbsyncer sys delete_cache_

For Normal operations now, everything will be fine. They process like Export just gone Take a bit longer at the first time, where the Cache is built with the operation.  But in some cases, that is not enough. As an Example, if the API Endpoints for Ansible take too long, they will run in a Timeout.  In these cases, you find an option to manually build this cache on the Command line
Example for Ansible: _./cmdbsyncer ansible update_cache_
In my example for what I build this Feature, the Time went down from 171 Seconds to just 2 Seconds for the hole Process 

