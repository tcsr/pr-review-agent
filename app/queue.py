from __future__ import annotations

from sqlalchemy import select, update, func

from app.models import Event
from app.store.tables import Job, DeadLetter


class Queue:
    def __init__(self, session_factory, max_attempts: int = 4):
        self.session_factory = session_factory
        self.max_attempts = max_attempts

    def enqueue(self, platform, repo, pr_number, head_sha, task) -> Job | None:
        with self.session_factory() as s:
            exists = s.execute(
                select(Job).where(
                    Job.platform == platform, Job.repo == repo,
                    Job.pr_number == pr_number, Job.head_sha == head_sha,
                    Job.task == task,
                )
            ).scalar_one_or_none()
            if exists is not None:
                return None
            job = Job(platform=platform, repo=repo, pr_number=pr_number,
                      head_sha=head_sha, task=task)
            s.add(job)
            s.commit()
            s.refresh(job)
            s.expunge(job)
            return job

    def enqueue_event(self, event: Event, tasks: list[str]) -> list[Job]:
        out = []
        for t in tasks:
            j = self.enqueue(event.platform.value, event.repo, event.pr_number,
                             event.head_sha, t)
            if j is not None:
                out.append(j)
        return out

    def claim(self) -> Job | None:
        with self.session_factory() as s:
            subq = (select(Job.id).where(Job.status == "pending")
                    .order_by(Job.id).limit(1).scalar_subquery())
            stmt = (update(Job).where(Job.id == subq)
                    .values(status="in_progress", attempts=Job.attempts + 1)
                    .returning(Job))
            job = s.execute(stmt).scalar_one_or_none()
            if job is None:
                return None
            s.commit()
            s.refresh(job)
            s.expunge(job)
            return job

    def complete(self, job_id: int) -> None:
        with self.session_factory() as s:
            job = s.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            job.status = "done"
            s.commit()

    def fail(self, job_id: int, error: str) -> None:
        with self.session_factory() as s:
            job = s.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            job.error = error
            if job.attempts < self.max_attempts:
                job.status = "pending"
            else:
                job.status = "failed"
                s.add(DeadLetter(job_id=job.id, last_error=error))
            s.commit()

    def stats(self) -> dict:
        out = {"pending": 0, "in_progress": 0, "done": 0, "failed": 0}
        with self.session_factory() as s:
            rows = s.execute(select(Job.status, func.count()).group_by(Job.status)).all()
        for status, count in rows:
            out[status] = count
        return out

    def _job_dict(self, j) -> dict:
        return {"id": j.id, "platform": j.platform, "repo": j.repo,
                "pr_number": j.pr_number, "head_sha": j.head_sha, "task": j.task,
                "status": j.status, "attempts": j.attempts, "error": j.error}

    def list_jobs(self, limit: int = 50) -> list[dict]:
        with self.session_factory() as s:
            rows = s.execute(select(Job).order_by(Job.id.desc()).limit(limit)).scalars().all()
            return [self._job_dict(j) for j in rows]

    def list_dead_letter(self, limit: int = 50) -> list[dict]:
        with self.session_factory() as s:
            rows = s.execute(
                select(DeadLetter).order_by(DeadLetter.id.desc()).limit(limit)
            ).scalars().all()
            return [{"id": d.id, "job_id": d.job_id, "last_error": d.last_error} for d in rows]

    def requeue(self, job_id: int) -> bool:
        with self.session_factory() as s:
            job = s.get(Job, job_id)
            if job is None:
                return False
            job.status = "pending"
            job.attempts = 0
            job.error = None
            s.commit()
            return True
