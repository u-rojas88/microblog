"""
Worker program to consume post creation jobs from Beanstalkd queue
and insert them into the database.
"""

import json
import os
import signal
import sys
from sqlalchemy.orm import Session
import greenstalk

# Handle both module import and direct execution
try:
    from .db import SessionLocal
    from .models import Post
except ImportError:
    # If running as __main__, adjust import path
    from timelines_service.db import SessionLocal
    from timelines_service.models import Post


BEANSTALKD_HOST = os.getenv("BEANSTALKD_HOST", "127.0.0.1")
BEANSTALKD_PORT = int(os.getenv("BEANSTALKD_PORT", "11300"))
POST_QUEUE = "post_creation"

# Graceful shutdown flag
shutdown_requested = False


def signal_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    print("\nShutdown signal received, finishing current job...")
    shutdown_requested = True


def process_post_job(job_data: dict, db: Session):
    """
    Process a single post creation job.
    
    Args:
        job_data: Dictionary containing username, user_id, text, repost_original_url
        db: Database session
    """
    try:
        post = Post(
            user_id=job_data["user_id"],
            text=job_data["text"],
            repost_original_url=job_data.get("repost_original_url"),
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        print(f"Created post {post.post_id} for user {job_data['username']}")
        return True
    except Exception as e:
        db.rollback()
        print(f"Error processing job: {e}", file=sys.stderr)
        return False


def main():
    """Main worker loop to consume jobs from Beanstalkd."""
    global shutdown_requested
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print(f"Starting post creation worker (Beanstalkd: {BEANSTALKD_HOST}:{BEANSTALKD_PORT})")
    
    try:
        # Connect to Beanstalkd
        client = greenstalk.Client((BEANSTALKD_HOST, BEANSTALKD_PORT))
        client.watch(POST_QUEUE)
        client.ignore("default")  # Only watch our queue
        
        print(f"Watching queue: {POST_QUEUE}")
        
        # Main processing loop
        while not shutdown_requested:
            try:
                # Reserve a job (blocks until one is available or timeout)
                job = client.reserve(timeout=1)
                
                if job is None:
                    # Timeout - check if we should shutdown
                    continue
                
                # Parse job data
                try:
                    job_data = json.loads(job.body)
                except json.JSONDecodeError as e:
                    print(f"Invalid JSON in job {job.id}: {e}", file=sys.stderr)
                    client.delete(job.id)
                    continue
                
                # Process the job
                db = SessionLocal()
                try:
                    success = process_post_job(job_data, db)
                    if success:
                        # Delete job on success
                        client.delete(job.id)
                    else:
                        # Bury job on failure (move to buried state)
                        client.bury(job.id)
                finally:
                    db.close()
                    
            except greenstalk.TimedOutError:
                # Timeout is expected, continue loop
                continue
            except Exception as e:
                print(f"Error in worker loop: {e}", file=sys.stderr)
                # Continue processing other jobs
                continue
        
        print("Worker shutting down gracefully...")
        
    except KeyboardInterrupt:
        print("\nWorker interrupted")
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            client.close()
        except:
            pass


if __name__ == "__main__":
    main()

