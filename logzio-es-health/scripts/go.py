#!/usr/bin/python

#
# Main docker script. Loops and query elasticsearch apis, and sends the info to Logz.io throught HTTPS.
# Its also cache the results locally so that nagios monitor can happen quickly on the docker.
#
# Written by Roi Rav-Hon @ Logz.io
#
# Params:
#	Mandatory:
#		LOGZ_TOKEN - Token from your logz.io settings page
#		ELASTICSEARCH_ADDR - Your cluster dns/address. We need to query it somehow, dont we? (currently support only http on port 9200)
#
#	Optional:
#		INTERVAL_SECONDS - What is the sample interval for cluster health and pending tasks.
#						   Note that it doesnt include the running time of the script.
#
#		CLUSTERSTATE_SECONDS - Sample interval of cluster state. This should be much higher since it is a "heavy" api call.
#							   Note again that it doesnt include the script running time.		
#
#		LISTENER - Logz.io listener address. Basicly should not be used outsize of logz.io
#
#
# All of the parameters should be supplemented to docker as environment variables.. e.g (docker run ... -e INTERVAL_SECONDS=4 ..)
#

import os, requests, datetime, time, sys, json, re
from threading import Thread, Condition

fthread = open("/thread", "w")
fmain = open("/main", "w")

# Gets optional variables
listener = os.getenv('LISTENER', 'listener.logz.io:8091')
interval = os.getenv('INTERVAL_SECONDS', 30)
stateInterval = os.getenv('CLUSTERSTATE_SECONDS', 3600)

# Get mandatory variables
logzToken = os.getenv('LOGZ_TOKEN')
elasticsearchAddr = os.getenv('ELASTICSEARCH_ADDR')

# Check if both mandatory are set
if not all([logzToken, elasticsearchAddr]):

	print ("#############################################################################################")
	print ("You must supply both your Logz.io token, and your your ElasticSearch ip/hostname")
	print ("docker run .... -e LOGZ_TOKEN=<Your Token> -e ELASTICSEARCH_ADDR=<Elasticsearch Address> ....")
	print ("#############################################################################################")

	sys.exit(1)

def queryClusterState():

	# Set up a conditional thread lock
	lock = Condition()

	# Aquire it 
	lock.acquire()

	# Constant monitor
	while True:

		# Get the current timestamp as kibana would love
		now = datetime.datetime.utcnow()
		kibanaTimestamp = now.strftime("%Y-%m-%dT%H:%M:%S") + ".%03d" % (now.microsecond / 1000) + "Z"

		# Get the clusterstate. can take a minute
		state = requests.get("http://{0}:9200/_cluster/state".format(elasticsearchAddr)).json()

		# Placeholder for jsons
		stateJsons = []

		# Get the cluster mapping size
		clusterStateSize = len(json.dumps(state["metadata"]["indices"]))

		# Creates a json of version and size
		returnJson = {

			"token" : logzToken,
			"@timestamp" : kibanaTimestamp,
			"type" : "elasticsearch-health",
			"clusterstate_version" : state["version"],
			"clusterstate_mapping_size" : clusterStateSize
		}

		# Open cache file
		stateFile = open('/clusterstate.txt','w')

		# Write cache
		stateFile.write("MAPPING_SIZE:{0}".format(clusterStateSize))

		# And close it
		stateFile.close()

		# Add json to list
		stateJsons.append(returnJson)

		# Now we want to figure out which index has which mapping size
		for index in state["metadata"]["indices"]:

			# Prefix placeholder (for non logz- indices)
			accountPrefix = index

			# Check if its logzio internal index
			if (re.match("^logz-*", index)):
				
				# Cut the prefix
				accountPrefix = "-".join(index.split("-")[:-1])

			# Creates a temp json
			tempJson = {

				"token" : logzToken,
				"@timestamp" : kibanaTimestamp,
				"type" : "elasticsearch-health",
				"clusterstate_index_name" : index,
				"clusterstate_index_prefix" : accountPrefix,
				"clusterstate_index_size" : len(json.dumps(state["metadata"]["indices"][index]["mappings"]))
			}

			# Append it to the list
			stateJsons.append(tempJson)

		# Iterate over the jsons and sends them
		for currJson in stateJsons:

			# Send it out!
			requests.post("https://{0}".format(listener), json=currJson)

		# Force free memory because python doesnt know we dont need that anymore for the next hour
		del stateJsons[:]
		del stateJsons

		# Delete the state json
		del state

		# Sleep for cluster state interval (using a conditional lock here because time.sleep causes deadlocks in some cases for some reason)
		lock.wait(stateInterval)


# Start a different thread to query cluster state
thread = Thread(target=queryClusterState)
thread.start()

# Looping untill the end of times. or the containers at least.
while True:

	# Get the current timestamp as kibana would love
	now = datetime.datetime.utcnow()
	kibanaTimestamp = now.strftime("%Y-%m-%dT%H:%M:%S") + ".%03d" % (now.microsecond / 1000) + "Z"

	# Creating an array of jsons to push to logz.io
	listJsons = []

	# Get the cluster health
	healthJson = requests.get("http://{0}:9200/_cluster/health".format(elasticsearchAddr)).json()

	# Append logz.io token
	healthJson[u"token"] = logzToken

	# Append the type
	healthJson[u"type"] = "elasticsearch-health"

	# Append the timestamp
	healthJson[u"@timestamp"] = kibanaTimestamp

	# Add it to list
	listJsons.append(healthJson)

	# Open cache
	healthFile = open('/clusterhealth.txt','w')

	# Write cache
	healthFile.write("INITIALIZING_SHARDS:{0}\n".format(healthJson["initializing_shards"]))
	healthFile.write("NUMBER_OF_PENDING_TASKS:{0}\n".format(healthJson["number_of_pending_tasks"]))
	healthFile.write("RELOCATING_SHARDS:{0}\n".format(healthJson["relocating_shards"]))
	healthFile.write("UNASSIGNED_SHARDS:{0}\n".format(healthJson["unassigned_shards"]))
	healthFile.write("STATUS:{0}\n".format(healthJson["status"]))

	# Close it
	healthFile.close()

	# Get the pending tasks
	tasksJson = requests.get("http://{0}:9200/_cluster/pending_tasks".format(elasticsearchAddr)).json()

	# Iterate over them
	for task in tasksJson['tasks']:

		# Append the logz.io token
		task[u"token"] = logzToken

		# Append the type
		task[u"type"] = "elasticsearch-health"

		# Append the timestamp
		task[u"@timestamp"] = kibanaTimestamp

		# Save it to the list
		listJsons.append(task)

	# Iterate over the jsons and sends them
	for currJson in listJsons:

		# Send it out!
		requests.post("https://{0}".format(listener), json=currJson)

	# Force free memory because python doesnt know we dont need that anymore for the next 30 seconds
	del listJsons[:]
	del listJsons

	# Sleeps for interval!
	time.sleep(interval)





