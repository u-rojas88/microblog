#gateway: PORT=${PORT:-8080} gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:$PORT gateway:app
registry: gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:$PORT registry_service.app:app
users: gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:$PORT users_service.app:app
timelines: gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:$PORT timelines_service.app:app
timelines_worker: PYTHONPATH=/home/ncc1701d/projects/microblog python -m timelines_service.workers
likes: gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:$PORT likes_service.app:app
likes_validation_worker: PYTHONPATH=/home/ncc1701d/projects/microblog python -m likes_service.workers
likes_notification_worker: PYTHONPATH=/home/ncc1701d/projects/microblog python -m likes_service.workers notification
polls: gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:$PORT polls_service.app:app

