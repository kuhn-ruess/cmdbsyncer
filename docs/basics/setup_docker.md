# Docker

The Project is not in the Docker Library yet, but you can run it after Checkout the Code.

The Docker Compose File there contains all the needed dependencies.
The Dockerfile you found already in the Main Directory of the repo, I guess.

And if you develop with the syncer, you may want to look into the ./helper command,
which provides you an environment with live refresh after code changes.




## Things to Consider

### MongoDB
The Project always needs his MongoDB, like the docker-compose.yml also defines. 


### Access to the container
To work with the Project, not all can be done in the Web interface. For example, for Debug and Testing, the Access to the Shell is needed. 

### Cron Jobs
The Syncer Needs Cron Jobs. These need to be triggerted using the docker exec command

### CSV Files
If you want to import CSV Files into the Syncer, make sure to define a Volume where you can place it.


### Resources
The Syncer does not need many Resources, mainly Disk Space. And at least two CPUs

### UWSGI/ NGINX
Inside the Container you will find a Python Application. Normally, they are accessed using UWSGI. And many Containers then also contain an NGINX in Front of this UWSGI.  The CMDB Syncer not has this Nginx, since it would be redundant. Most likely, the Reverse proxy in Front of the Container will be a Nginx anyway. And so, your Reverse Proxy can speak directly UWSGI with the Container

