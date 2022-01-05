#!/usr/bin/python3

# - Using the iot_client.py from aws-iot-device-management-with-fleet-hub-demo on Github
#   https://github.com/aws-samples/aws-iot-device-management-with-fleet-hub-demo/
# - This code is modified to fit this FleetHub lab

import os
import sys
import time
import json
import uuid
import random
import tempfile
import requests
import logging
import argparse
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from AWSIoTPythonSDK.core.protocol.connection.cores import ProgressiveBackOffCore
from AWSIoTPythonSDK.exception.AWSIoTExceptions import connectTimeoutException

parser = argparse.ArgumentParser(description="Demo Client")
parser.add_argument('--thing', help="File path to thing client, private key, aonf config.")
parser.add_argument('--endpoint', help="File path to thing client, private key, aonf config.")
args = parser.parse_args()

# Configure logging
logger = logging.getLogger("AWSIoTPythonSDK.core")
logger.setLevel(logging.ERROR)
streamHandler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
streamHandler.setFormatter(formatter)
logger.addHandler(streamHandler)
per_thread_message_count = 1
backOffCore = ProgressiveBackOffCore()
device_location = random.choice(['nyc', 'atl', 'bos'])

class IoTThing(AWSIoTMQTTClient):
    def __init__(self, name, path, endpoint):
        self.serial_number = name
        self.thing_name = name
        self.thing_path = path
        self.iot_endpoint = endpoint
        self.pri_key = self.thing_path + "private.key"
        self.cert_pem = self.thing_path + "certificate.pem"
        self.root_ca = self.thing_path + "rootCA.pem"
        print("Using endpoint: {0}".format(self.iot_endpoint))
        super().__init__(self.serial_number)
        # AWSIoTMQTTClient connection configuration
        self.configureEndpoint(self.iot_endpoint, 8883)
        self.configureAutoReconnectBackoffTime(1, 32, 20)
        self.configureOfflinePublishQueueing(-1)  # Infinite offline Publish queueing
        self.configureDrainingFrequency(20)  # Draining: 2 Hz
        self.configureConnectDisconnectTimeout(10)  # 10 sec
        self.configureMQTTOperationTimeout(10)  # 5 sec
        # End MQTT client configuration
        self.initial_shadow = {
            "battery": random.choice([1, 10, 30, 90]),
            "firmware": random.choice(["0.1", "1.0", "1.5", "2.0"]),
            "temperature": random.choice([15, 25, 29]),
            "location": device_location
        }
        self.shadow = self.initial_shadow
        print("Initialized new thing with serial: {0}".format(self.serial_number))
        self.mqtt_client = None
        self.certificate_ownership_token = None
        self.cert_id = None
        self.app_mqtt_client = None
        self.open_jobs = dict()
        self.boto_session = None
        self.send_heartbeats = True
        self.wan_connection = 1

    def init_app_mqtt_client(self):
        print("Connecting MQTT client")
        self.configureCredentials(self.root_ca, self.pri_key, self.cert_pem)
        attempts = 0
        time.sleep(1)
        while attempts < 5:
            try:
                self.connect()
                print("MQTT client connected")
                break
            except connectTimeoutException:
                print("Connection timed out, trying again")
                attempts += 1
                continue
        else:
            print("Too many attempts")
            raise Exception
        self.shadow_listener()
        print("Initialized shadow listener")
        print("Reporting initial shadow")
        self.report_shadow(self.shadow)
        self.init_jobs_client()
        print("IoT Client initialization completed")

    # Handle communication with AWS IoT Shadow Service
    def shadow_listener(self, shadow_name=None):
        if shadow_name:
            self.subscribe("$aws/things/{0}/shadow/name/{1}/update/accepted".format(self.thing_name, shadow_name), 1, self.shadow_callback)
        else:
            self.subscribe("$aws/things/{0}/shadow/update/accepted".format(self.thing_name), 1, self.shadow_callback)

    def report_shadow(self, shadow_value, shadow_name=None, clear_desired=False):
        new_shadow = {
            "state": {
                "reported": shadow_value
            }
        }
        if shadow_name:
            shadow_topic = "$aws/things/{0}/shadow/name/{1}/update".format(self.thing_name, shadow_name)
        else:
            shadow_topic = "$aws/things/{0}/shadow/update".format(self.thing_name)

        if clear_desired:
            new_shadow['state']['desired'] = None
        self.publish(shadow_topic, json.dumps(new_shadow), 0)
        print("Reported shadow of:")
        print(shadow_value)

    def shadow_callback(self, _0, _1, message):
        payload = json.loads(message.payload)['state']
        print("Received a shadow update: ")
        print(payload)
        print("from topic: ")
        print(message.topic)
        print("--------------\n\n")
        if "desired" in payload.keys():
            if payload["desired"]:
                self.update_device_configuration_from_shadow_update(payload)
            else:
                print("No changes requested")
        else:
            print("No changes requested")

    def update_device_configuration_from_shadow_update(self, updated_shadow):
        time.sleep(3)
        for key, value in updated_shadow['desired'].items():
            if key == "heartbeat":
                self.send_heartbeats = value
            self.shadow[key] = value
        self.report_shadow(self.shadow, clear_desired=True)

    # Handle communication with AWS IoT Jobs Service
    def init_jobs_client(self):
        print("Checking for outstanding jobs")
        self.subscribe("$aws/things/{0}/jobs/get/accepted".format(self.thing_name), 0, self.init_jobs_response)
        print("Subscribing to jobs detail topic")
        self.subscribe(
            "$aws/things/{0}/jobs/+/get/accepted".format(self.thing_name),
            0,
            self.job_detail_callback
        )
        self.publish(
            "$aws/things/{0}/jobs/get".format(self.thing_name),
            json.dumps({"clientToken": str(uuid.uuid4())}),
            0
        )
        time.sleep(2)
        print("Initializing new jobs listener")
        self.subscribe("$aws/things/{0}/jobs/notify".format(self.thing_name), 0, self.jobs_notification_callback)

    def init_jobs_response(self, _0, _1, message):
        payload = json.loads(message.payload)
        if "queuedJobs" in payload.keys():
            if payload['queuedJobs']:
                print("Existing queued jobs:")
                print(payload['queuedJobs'])
                self.jobs_handler(payload['queuedJobs'])
        if "inProgressJobs" in payload.keys():
            if payload['inProgressJobs']:
                print("Existing In-Progress Jobs")
                print(payload['inProgressJobs'])
                self.jobs_handler(payload['inProgressJobs'])

    def jobs_notification_callback(self, _0, _1, message):
        payload = json.loads(message.payload)
        print("Received new Jobs: ")
        print(payload)
        print("--------------\n\n")
        if 'QUEUED' in payload['jobs'].keys():
            self.jobs_handler(payload['jobs']['QUEUED'])

    def jobs_handler(self, jobs):
        for j in jobs:
            print("Processing job: {0}".format(j['jobId']))
            get_job_payload = {
                "clientToken": str(uuid.uuid4()),
                "includeJobDocument": True
            }
            base_job_topic = "$aws/things/{0}/jobs/{1}/".format(self.thing_name, j['jobId'])
            self.publish(
                "{0}get".format(base_job_topic),
                json.dumps(get_job_payload),
                0
            )

    def job_detail_callback(self, _0, _1, message):
        job_detail = json.loads(message.payload)['execution']
        print("Received job details:")
        print(job_detail)
        self.open_jobs[job_detail['jobId']] = job_detail
        self.acknowledge_job(job_detail['jobId'])
        operation, success = self.execute_job(job_detail['jobId'])
        if success:
            status = "SUCCEEDED"
        elif operation and not success:
            status = "FAILED"
        else:
            status = "REJECTED"
        set_final_job_status = {
            "status": status
        }
        print("Notifying AWS IoT of status, {0}, of job: {1}".format(status, job_detail['jobId']))
        self.publish(
            "$aws/things/{0}/jobs/{1}/update".format(self.thing_name, job_detail['jobId']),
            json.dumps(set_final_job_status),
            0
        )
        print("Removing job from open jobs")
        del(self.open_jobs[job_detail['jobId']])
        # self.unsubscribe(message.topic)

    def acknowledge_job(self, job_id):
        print("Acknowledging job {0} as IN_PROGRESS to IoT Jobs".format(job_id))
        set_job_to_pending_payload = {
            "status": "IN_PROGRESS",
            "clientToken": str(uuid.uuid4())
        }
        self.publish(
            "$aws/things/{0}/jobs/{1}/update".format(self.thing_name, job_id),
            json.dumps(set_job_to_pending_payload),
            0
        )

    def execute_job(self, job_id):
        job_details = self.open_jobs[job_id]
        job_document = job_details['jobDocument']
        if 'operation' in job_document.keys():
            if job_document['operation'] == "FIRMWARE_UPGRADE":
                self.firmware_upgrade(job_document)
            elif job_document['operation'] == "ORDER_66":
                self.demo_connectivity_issues()
            elif job_document['operation'] == "REBOOT":
                self.reboot()
            else:
                print("Successfully performed {0} on device".format(job_document['operation']))
            return job_document['operation'], True
        else:
            print("Missing operation to be performed in job")
            return None, False

    @staticmethod
    def subscribe_callback(_0, _1, message):
        payload = json.loads(message.payload)
        print("Received a message: ")
        print(payload)
        print("from topic: ")
        print(message.topic)
        print("--------------\n\n")

    def firmware_upgrade(self, job_document):
        self.shadow['firmware'] = job_document['firmware_version']
        self.report_shadow({"firmware": job_document['firmware_version']})

    def heartbeater(self):
        while True:
            if self.send_heartbeats:
                print("Sending heartbeat message")
                try:
                    self.publish("demofleet/{0}/heartbeat".format(self.thing_name), "alive", 1)
                except AWSIoTPythonSDK.exception.AWSIoTExceptions.publishTimeoutException as e:
                    print("AWSIoTPythonSDK.exception.AWSIoTExceptions.publishTimeoutException")
                    print(e)
                except publishTimeoutException as e:
                    print("publishTimeoutException")
                    print(e)
                if self.shadow['temperature'] != 100:
                    new_shadow = {"desired": {"temperature": random.choice([10, 11, 12, 13, 14, 15, 16])}}
                    self.update_device_configuration_from_shadow_update(new_shadow)
                    print("Updated shadow with new temperature: {0}".format(new_shadow['desired']['temperature']))
            time.sleep(3)

    def demo_connectivity_issues(self):
        if self.shadow['battery'] < 3:
            print("Battery low, shutting down")
            self.send_heartbeats = False
            time.sleep(2)
            self.disconnect()
            sys.exit(0)
        elif self.shadow['firmware'] == "0.1":
            print("Unhandled exception")
            sys.exit(1)
        elif self.shadow['location'] == 'atl':
            print("Temperature sensor stopped working, changing to 100")
            new_shadow = {"desired": {"temperature": 100}}
            self.update_device_configuration_from_shadow_update(new_shadow)
        elif self.shadow['firmware'] == "1.0":
            print("Minor bug in old firmware, can no longer update telemetry data")
            self.send_heartbeats = False

    def reboot(self):
        print("Rebooting device")
        self.send_heartbeats = False
        time.sleep(3)
        print("Disconnecting MQTT")
        self.disconnectAsync()
        time.sleep(3)
        self.connect()
        self.shadow_listener()
        self.init_jobs_client()
        self.heartbeater()


if __name__ == "__main__":
    endpoint = args.endpoint
    thing_name = args.thing
    thing_path = "/home/ec2-user/workspace/devices/" + thing_name + "/"
    thing = IoTThing(thing_name, thing_path, endpoint)
    thing.init_app_mqtt_client()
    thing.heartbeater()
