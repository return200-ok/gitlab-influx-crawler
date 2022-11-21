import json
import logging
import os
from datetime import datetime, timedelta
from os import environ
from time import time

import rfc3339
from dotenv import load_dotenv
from influx_client import InfluxClient, InfluxPoint
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import ASYNCHRONOUS
from multi_process import *

import gitlab

# Load env
load_dotenv()
gl = gitlab.Gitlab(url=os.getenv('GITLAB_URL'), private_token=os.getenv('GITLAB_PRIVATE_TOKEN'))
influx_token = os.getenv('INFLUX_TOKEN')
influx_server = os.getenv('INFLUX_DB')
org_name = os.getenv('INFLUX_ORG')
bucket_name = os.getenv('BUCKET_NAME')
before_day = float(os.getenv('BEFORE_DAY'))



'''
    Config logging handler
'''
def get_date_string(date_object):
  return rfc3339.rfc3339(date_object)

duration_time = datetime.now() - timedelta(before_day)
logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
rootLogger = logging.getLogger()
logPath = "logs"
fileName = get_date_string(datetime.now())+'_gitlab_collecter'
fileHandler = logging.FileHandler("{0}/{1}.log".format(logPath, fileName))
fileHandler.setFormatter(logFormatter)
rootLogger.addHandler(fileHandler)

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
rootLogger.addHandler(consoleHandler)
logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

# List projects
'''
    UserWarning: Calling a `list()` method without specifying `get_all=True` or `iterator=True` 
    will return a maximum of 20 items. Your query returned 20 of many items. 
    See https://python-gitlab.readthedocs.io/en/v3.11.0/api-usage.html#pagination for more details. 
    If this was done intentionally, 
    then this warning can be supressed by adding the argument `get_all=False` to the `list()` call.
'''
def get_projects():
    projects = gl.projects.list(get_all=True)
    return projects

def get_project_size(project):
    project_id = project.id
    project_size = gl.projects.get(id=project_id,statistics=True)
    return project_size

#Get the list of branches for a repository
def get_branches(project):
    branches = project.branches.list(created_after=duration_time)
    return branches

#List the commits for a project
def get_commits(project):
    commits = project.commits.list(created_after=duration_time)
    return commits

#List the project issues
def get_issues(project):
    issues = project.issues.list(created_after=duration_time)
    return issues

#List MRs/Pull-request for a project
def get_mrs(project):
    mrs = project.mergerequests.list(created_after=duration_time)
    return mrs

class Stats:
    def __init__(self, statistics):
        self.statistics = statistics

#Create Commits object
class Commits:
    def __init__(self, id, short_id, title, created_at, author_email):
        self.id = id
        self.short_id = short_id
        self.title = title
        self.created_at = created_at
        self.author_email = author_email
  
#Create Issues object
class Issues:
    def __init__(self, id, project_id, title, state, created_at, updated_at):
        self.id = id
        self.project_id = project_id
        self.title = title
        self.state = state
        self.created_at = created_at
        self.updated_at = updated_at  

#Create MRs/Pull-request object
class Mrs:
    def __init__(self, id, project_id, title, state, created_at, updated_at, target_branch, source_branch):
        self.id = id
        self.project_id = project_id
        self.title = title
        self.state = state
        self.created_at = created_at
        self.updated_at = updated_at  
        self.target_branch = target_branch
        self.source_branch = source_branch

#Gen data point
def gen_datapoint(kpi_type, kpi_data, i):
    if kpi_type == "mrs":
        data = Mrs(kpi_data[i].id, kpi_data[i].project_id, kpi_data[i].title, kpi_data[i].state, kpi_data[i].created_at, kpi_data[i].updated_at, kpi_data[i].target_branch, kpi_data[i].source_branch)
        measurement = project.id
        tags = {
            "project_name": project.name,
            "mrs_id": data.id,
            "mrs_title": data.title,
            "state": data.state,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
            "target_branch": data.target_branch,
            "source_branch": data.source_branch,
            }
        timestamp = int(time())
        fields = {
            "mrs_id": data.id
            }
        data_point = InfluxPoint(measurement, tags, fields, timestamp)._point
        return data_point
    elif kpi_type == "issue":
        data = Issues(kpi_data[i].id, kpi_data[i].project_id, kpi_data[i].title, kpi_data[i].state, kpi_data[i].created_at, kpi_data[i].updated_at)
        measurement = project.id
        tags = {
            "project_name": project.name,
            "issue_id": data.id,
            "issue_title": data.title,
            "issue_state": data.state,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
            }
        timestamp = int(time())
        fields = {
            "issue_id": data.id
            }
        data_point = InfluxPoint(measurement, tags, fields, timestamp)._point
        return data_point
    elif kpi_type == "commit":
        data = Commits(kpi_data[i].id, kpi_data[i].short_id, kpi_data[i].title, kpi_data[i].created_at, kpi_data[i].author_email)
        measurement = project.id
        tags = {
            "project_name": project.name,
            "commit_id": data.id,
            "commit_title": data.title,
            "created_at": data.created_at,
            "author_email": data.author_email,
            }
        timestamp = int(time())
        fields = {
            "commit_id": data.short_id
            }
        data_point = InfluxPoint(measurement, tags, fields, timestamp)._point
        return data_point
    elif kpi_type == "statistics":
        data = Stats(kpi_data[i].statistics)
        measurement = project.id
        tags = data.statistics
        timestamp = int(time())
        fields = {
            "project_id": project.id
            }
        data_point = InfluxPoint(measurement, tags, fields, timestamp)._point
        return data_point
    else:
        logging.warning("kpi_type is not matching!")


def push_data(kpi, data):
    client.check_connection()
    client.check_write()
    if len(data) > 0:
        for i in range(0, len(data)):
            data_point = gen_datapoint(kpi, data, i)
            try:
                # client.write_data(data_point)
                write_multiprocess(data_point)
                logging.info("Wrote "+str(data_point)+" to bucket "+bucket_name)
            except Exception as e:
                logging.error("Problem inserting points for current batch")
                raise e

if __name__ == '__main__':
    client = InfluxClient(influx_server, influx_token, org_name, bucket_name)
    projects = get_projects()
    kpis = ["mrs", "issue", "commit", "statistics"]
    start_time = datetime.now()
    for kpi in kpis:
        if kpi == "mrs":
            for project in projects:
                mrs = get_mrs(project)
                push_data(kpi, mrs)
        elif kpi == "issue":
            for project in projects:
                issue = get_issues(project)
                push_data(kpi, issue)
        elif kpi == "commit":
            for project in projects:
                commit = get_commits(project)
                push_data(kpi, commit)
        elif kpi == "statistics":
            for project in projects:
                statistics = []
                statistics.append(get_project_size(project))
                push_data(kpi, statistics)

    print()
    logging.info(f'Import finished in: {datetime.now() - start_time}')
    print()
    client.close_process()