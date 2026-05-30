import os

from celery import Celery

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery = Celery(
    "claims",
    broker=redis_url,
    backend=redis_url,
    include=[
        "app.tasks.generators",
        "app.tasks.submission",
        "app.tasks.remittance",
        "app.tasks.replay",
    ],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "background-generators": {
            "task": "app.tasks.generators.run_background_generators",
            "schedule": 30.0,
        },
    },
)
