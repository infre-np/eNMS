from datetime import datetime
from multiprocessing.pool import ThreadPool
from sqlalchemy import Boolean, Column, ForeignKey, Integer, PickleType, String
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import backref, relationship
from time import sleep

from eNMS import db
from eNMS.base.associations import (
    job_device_table,
    job_pool_table,
    job_workflow_table
)
from eNMS.base.custom_base import CustomBase
from eNMS.base.helpers import retrieve
from eNMS.base.properties import cls_to_properties


class Job(CustomBase):

    __tablename__ = 'Job'

    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True)
    description = Column(String)
    positions = Column(MutableDict.as_mutable(PickleType), default={})
    logs = Column(MutableDict.as_mutable(PickleType), default={})
    tasks = relationship('Task', back_populates='job')
    type = Column(String)
    waiting_time = Column(Integer, default=0)
    workflows = relationship(
        'Workflow',
        secondary=job_workflow_table,
        back_populates='jobs'
    )
    devices = relationship(
        'Device',
        secondary=job_device_table,
        back_populates='jobs'
    )
    pools = relationship(
        'Pool',
        secondary=job_pool_table,
        back_populates='jobs'
    )

    __mapper_args__ = {
        'polymorphic_identity': 'Job',
        'polymorphic_on': type
    }

    def job_sources(self, workflow, type='all'):
        return [
            x.source for x in self.sources
            if (type == 'all' or x.type == type) and x.workflow == workflow
        ]

    def job_successors(self, workflow, type='all'):
        return [
            x.destination for x in self.destinations
            if (type == 'all' or x.type == type) and x.workflow == workflow
        ]

    def compute_targets(self):
        targets = set(self.devices)
        for pool in self.pools:
            targets |= set(pool.devices)
        return targets


class Service(Job):

    __tablename__ = 'Service'

    id = Column(Integer, ForeignKey('Job.id'), primary_key=True)
    private = {'id'}

    __mapper_args__ = {
        'polymorphic_identity': 'service',
    }

    @property
    def properties(self):
        return {p: getattr(self, p) for p in cls_to_properties['Service']}

    @property
    def column_values(self):
        serialized_object = self.properties
        for col in self.__table__.columns:
            value = getattr(self, col.key)
            serialized_object[col.key] = value
        serialized_object['devices'] = [
            obj.properties for obj in getattr(self, 'devices')
        ]
        serialized_object['pools'] = [
            obj.properties for obj in getattr(self, 'pools')
        ]
        return serialized_object

    def run(self, payload=None, targets=None):
        if self.has_targets:
            # payload and targets come from the workflow.
            # if the service is run outside the context of a workflow, we use
            # the services targets
            # if it runs inside a workflow, and the workflow has devices of
            # its own, targets will be set to the workflow devices
            if not targets:
                targets = self.compute_targets()
            results = {'success': True, 'devices': {}}
            pool = ThreadPool(processes=len(targets))
            pool.map(
                self.device_run,
                [(device, results, payload) for device in targets]
            )
            pool.close()
            pool.join()
        else:
            results = self.job(payload)
        self.logs[str(datetime.now())] = results
        db.session.commit()
        return results

    def device_run(self, args):
        device, results, payload = args
        try:
            results[device.name] = self.job(device, results, payload)
        except Exception as e:
            results[device.name] = {'success': False, 'result': str(e)}
        if not results[device.name]['success']:
            results['success'] = False

    @property
    def serialized(self):
        properties = self.properties
        properties['devices'] = [
            obj.properties for obj in getattr(self, 'devices')
        ]
        properties['pools'] = [
            obj.properties for obj in getattr(self, 'pools')
        ]
        properties['tasks'] = [
            obj.properties for obj in getattr(self, 'tasks')
        ]
        return properties


service_classes = {}


class WorkflowEdge(CustomBase):

    __tablename__ = 'WorkflowEdge'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    type = Column(Boolean)
    source_id = Column(Integer, ForeignKey('Job.id'))
    source = relationship(
        'Job',
        primaryjoin='Job.id == WorkflowEdge.source_id',
        backref=backref('destinations', cascade='all, delete-orphan'),
        foreign_keys='WorkflowEdge.source_id'
    )
    destination_id = Column(Integer, ForeignKey('Job.id'))
    destination = relationship(
        'Job',
        primaryjoin='Job.id == WorkflowEdge.destination_id',
        backref=backref('sources', cascade='all, delete-orphan'),
        foreign_keys='WorkflowEdge.destination_id'
    )
    workflow_id = Column(Integer, ForeignKey('Workflow.id'))
    workflow = relationship(
        'Workflow',
        back_populates='edges',
        foreign_keys='WorkflowEdge.workflow_id'
    )

    @property
    def serialized(self):
        properties = self.properties
        properties['source'] = self.source.serialized
        properties['destination'] = self.destination.serialized
        return properties


class Workflow(Job):

    __tablename__ = 'Workflow'

    id = Column(Integer, ForeignKey('Job.id'), primary_key=True)
    vendor = Column(String)
    operating_system = Column(String)
    jobs = relationship(
        'Job',
        secondary=job_workflow_table,
        back_populates='workflows'
    )
    edges = relationship('WorkflowEdge', back_populates='workflow')
    start_job = Column(Integer)
    end_job = Column(Integer)

    __mapper_args__ = {
        'polymorphic_identity': 'workflow',
    }

    def run(self, workflow=None):
        runtime = str(datetime.now())
        start_job = retrieve(Job, id=self.start_job)
        if not start_job:
            return False, {runtime: 'No start task in the workflow.'}
        jobs, visited = [start_job], set()
        workflow_results = {}
        while jobs:
            job = jobs.pop()
            # We check that all predecessors of the job have been visited
            # to ensure that the job will receive the full payload.
            # If it isn't the case, we put it back in the heap and move on to
            # another job.
            if any(n not in visited for n in job.job_sources(self)):
                continue
            visited.add(job)
            job_results = job.run(workflow_results)
            success = job_results['success']
            if job.id == self.end_job:
                workflow_results['success'] = success
            for successor in job.job_successors(self, success):
                if successor not in visited:
                    jobs.append(successor)
            workflow_results[job.name] = job_results
            sleep(job.waiting_time)
        self.logs[runtime] = workflow_results
        db.session.commit()
        return workflow_results

    @property
    def serialized(self):
        properties = self.properties
        properties['tasks'] = [
            obj.properties for obj in getattr(self, 'tasks')
        ]
        properties['jobs'] = [
            obj.properties for obj in getattr(self, 'jobs')
        ]
        properties['edges'] = [edge.serialized for edge in self.edges]
        properties['devices'] = [
            obj.properties for obj in getattr(self, 'devices')
        ]
        properties['pools'] = [
            obj.properties for obj in getattr(self, 'pools')
        ]
        return properties
