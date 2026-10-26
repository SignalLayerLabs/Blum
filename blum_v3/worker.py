"""Separate worker process; API reads never execute research or paper jobs."""
import logging
from uuid import uuid4

from .jobs import JobService
from .research import ResearchService
from .paper import PaperService
from .providers import fetch_history
from .domain import utc

logger=logging.getLogger(__name__)


class Worker:
    def __init__(self,repository,*,clock=None):
        self.repository=repository;self.jobs=JobService(repository,**({'clock':clock} if clock else {}));self.owner=uuid4().hex

    def run_once(self):
        job=self.jobs.claim(self.owner)
        if job is None:return False
        try:
            data=job['input'];kind=job['kind']
            def progress():
                current=self.jobs.get(job['id'])
                return current['status']=='RUNNING' and current['lease_token']==job['lease_token'] and utc(current['lease_until'])>self.jobs.clock()
            if kind=='research':result={'experiment_id':ResearchService(self.repository).run(data['experiment_id'],progress=progress)['id']}
            elif kind=='confirmation':result={'experiment_id':ResearchService(self.repository).confirm(data['experiment_id'],progress=progress)['id']}
            elif kind=='history':
                dataset=fetch_history(**data);self.repository.save_dataset(dataset)
                result=dict(dataset_id=dataset.dataset_id,accepted=len(dataset.bars),rejected=len(dataset.rejected))
            elif kind=='paper_step':result=PaperService(self.repository).step(**data,progress=progress)
            elif kind=='paper_cycle':
                cycles=PaperService(self.repository).cycle(progress=progress)
                result={'subscriptions':len(cycles),'outcomes':[{k:r[k] for k in ['account_id','fills','exclusions','decision_blocker'] if k in r} for r in cycles]}
            else:raise ValueError('unknown_job_type')
            self.jobs.finish(job['id'],job['lease_token'],result)
        except Exception as error:
            # Error text from providers/SQL can contain URLs or credentials; expose closed codes only.
            logger.warning('job_failed id=%s type=%s',job['id'],type(error).__name__)
            try:self.jobs.finish(job['id'],job['lease_token'],error='job_failed_'+type(error).__name__)
            except ValueError:pass # Canceled or lease transferred; the current owner controls status.
        return True
