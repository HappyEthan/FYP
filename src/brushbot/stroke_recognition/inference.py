"""Bounded latest-preview scheduling with lossless, higher-priority final jobs."""
from collections import deque
from dataclasses import dataclass
from queue import Queue
import threading
import time

from brushbot.stroke_classification.data import Stroke
from brushbot.stroke_classification.features import extract
from brushbot.stroke_classification.predict import predict_strokes
from .history import LoadedModel


@dataclass(frozen=True)
class PredictionJob:
    session_id: str
    stroke_id: int
    kind: str
    model: LoadedModel
    record: dict
    first: int
    last: int


def evaluate_job(job):
    started = time.perf_counter()
    result = dict(session_id=job.session_id, stroke_id=job.stroke_id, kind=job.kind,
                  model_token=job.model.token, model_sha256=job.model.sha256,
                  first=job.first, last=job.last, predicted=None, label=None,
                  scores=None, status='unavailable', error=None)
    try:
        features = extract(job.record, job.first, job.last, job.model.config)
        stroke = Stroke(sample_id=f'{job.session_id}:{job.stroke_id}', run_id=job.session_id,
                        label=None, index=job.stroke_id, label_source='unlabelled-live',
                        source_metadata=dict(kind=job.kind), **features)
        predicted = predict_strokes(job.model.bundle, [stroke])[0]
        result.update(status='ok', predicted=predicted['predicted'],
                      label=job.model.labels[predicted['predicted']], scores=predicted['scores'])
    except Exception as exc:
        result['error'] = str(exc) or type(exc).__name__
    result['elapsed_ms'] = (time.perf_counter()-started)*1000
    return result


class InferenceWorker:
    def __init__(self, evaluator=evaluate_job, max_finals=32):
        self.evaluator = evaluator
        self.max_finals = max_finals
        self.results = Queue()
        self._finals = deque()
        self._preview = None
        self._closing = False
        self._condition = threading.Condition()
        self.thread = threading.Thread(target=self._run, name='stroke-inference', daemon=True)
        self.thread.start()

    def submit(self, job):
        with self._condition:
            if self._closing:
                return False
            if job.kind == 'final':
                if len(self._finals) >= self.max_finals:
                    return False
                self._finals.append(job)
                if self._preview and (self._preview.session_id,self._preview.stroke_id) == (job.session_id,job.stroke_id):
                    self._preview = None
            else:
                self._preview = job
            self._condition.notify()
        return True

    def discard_preview(self):
        with self._condition:
            self._preview = None

    @property
    def pending_finals(self):
        with self._condition:
            return len(self._finals)

    def close(self):
        with self._condition:
            self._closing = True
            self._preview = None
            self._condition.notify_all()
        self.thread.join()

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closing or self._finals or self._preview is not None)
                if self._finals:
                    job = self._finals.popleft()
                elif self._closing:
                    return
                else:
                    job, self._preview = self._preview, None
            try:
                result = self.evaluator(job)
            except Exception as exc:
                result = dict(session_id=job.session_id, stroke_id=job.stroke_id, kind=job.kind,
                              model_token=job.model.token, model_sha256=job.model.sha256,
                              first=job.first, last=job.last, status='unavailable',
                              error=str(exc), predicted=None, label=None, scores=None, elapsed_ms=0.)
            self.results.put(result)
