"""
Worker programs for likes service:
1. Validation worker - validates posts exist and removes invalid likes
2. Notification worker - sends email notifications when posts are liked
"""

import json
import os
import signal
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import httpx
import greenstalk

# Handle both module import and direct execution
try:
    from .db import get_redis
    from registry_service.discovery import get_service_url_sync
except ImportError:
    from likes_service.db import get_redis
    from registry_service.discovery import get_service_url_sync


BEANSTALKD_HOST = os.getenv("BEANSTALKD_HOST", "127.0.0.1")
BEANSTALKD_PORT = int(os.getenv("BEANSTALKD_PORT", "11300"))
LIKE_VALIDATION_QUEUE = "like_validation"
LIKE_NOTIFICATION_QUEUE = "like_notification"

# Email configuration
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "25"))
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@microblog.local")

# Graceful shutdown flag
shutdown_requested = False


def signal_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    print("\nShutdown signal received, finishing current job...")
    shutdown_requested = True


def likes_key_for_post(post_id: int) -> str:
    return f"likes:post:{post_id}"


def likes_key_for_user(username: str) -> str:
    return f"likes:user:{username}"


def likes_score_key() -> str:
    return "likes:score"


def remove_like_from_redis(post_id: int, username: str):
    """Remove a like from Redis."""
    r = get_redis()
    r.srem(likes_key_for_post(post_id), username)
    r.srem(likes_key_for_user(username), post_id)
    # Decrement score
    r.zincrby(likes_score_key(), -1, str(post_id))
    score = r.zscore(likes_score_key(), str(post_id))
    if score is not None and score <= 0:
        r.zrem(likes_score_key(), str(post_id))


def send_email(to_email: str, subject: str, body: str):
    """Send an email using SMTP."""
    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}", file=sys.stderr)
        return False


def validate_post_worker():
    """Worker to validate posts and remove invalid likes."""
    global shutdown_requested
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print(f"Starting like validation worker (Beanstalkd: {BEANSTALKD_HOST}:{BEANSTALKD_PORT})")
    
    try:
        client = greenstalk.Client((BEANSTALKD_HOST, BEANSTALKD_PORT))
        client.watch(LIKE_VALIDATION_QUEUE)
        client.ignore("default")
        
        print(f"Watching queue: {LIKE_VALIDATION_QUEUE}")
        
        while not shutdown_requested:
            try:
                job = client.reserve(timeout=1)
                
                if job is None:
                    continue
                
                try:
                    job_data = json.loads(job.body)
                    post_id = job_data["post_id"]
                    username = job_data["username"]
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"Invalid job data: {e}", file=sys.stderr)
                    client.delete(job.id)
                    continue
                
                # Validate post exists by querying timelines service
                timelines_service_url = get_service_url_sync("timelines")
                if not timelines_service_url:
                    print(f"Timelines service not available, burying job {job.id}", file=sys.stderr)
                    client.bury(job.id)
                    continue
                
                # Check if the specific post exists
                try:
                    with httpx.Client(timeout=5.0) as http_client:
                        resp = http_client.get(f"{timelines_service_url}/posts/id/{post_id}")
                        
                        if resp.status_code == 200:
                            # Post exists - validation passed
                            client.delete(job.id)
                            continue
                        elif resp.status_code == 404:
                            # Post doesn't exist - remove like and notify user
                            print(f"Post {post_id} not found, removing like from {username}")
                            remove_like_from_redis(post_id, username)
                            
                            # Get user email and send notification
                            users_service_url = get_service_url_sync("users")
                            if users_service_url:
                                try:
                                    with httpx.Client(timeout=5.0) as http_client:
                                        user_resp = http_client.get(f"{users_service_url}/users/{username}")
                                        if user_resp.status_code == 200:
                                            user_data = user_resp.json()
                                            user_email = user_data.get("email")
                                            if user_email:
                                                subject = "Invalid Like Removed"
                                                body = f"Hello {username},\n\nYour like on post {post_id} has been removed because the post no longer exists.\n\nBest regards,\nMicroblog Team"
                                                send_email(user_email, subject, body)
                                except Exception as e:
                                    print(f"Failed to notify user {username}: {e}", file=sys.stderr)
                            
                            client.delete(job.id)
                            continue
                        else:
                            # Unexpected status code
                            print(f"Unexpected status {resp.status_code} when validating post {post_id}", file=sys.stderr)
                            client.bury(job.id)
                            continue
                            
                except httpx.HTTPStatusError as e:
                    # Handle HTTP errors
                    if e.response.status_code == 404:
                        # Post doesn't exist
                        print(f"Post {post_id} not found, removing like from {username}")
                        remove_like_from_redis(post_id, username)
                        
                        # Get user email and send notification
                        users_service_url = get_service_url_sync("users")
                        if users_service_url:
                            try:
                                with httpx.Client(timeout=5.0) as http_client:
                                    user_resp = http_client.get(f"{users_service_url}/users/{username}")
                                    if user_resp.status_code == 200:
                                        user_data = user_resp.json()
                                        user_email = user_data.get("email")
                                        if user_email:
                                            subject = "Invalid Like Removed"
                                            body = f"Hello {username},\n\nYour like on post {post_id} has been removed because the post no longer exists.\n\nBest regards,\nMicroblog Team"
                                            send_email(user_email, subject, body)
                            except Exception as e:
                                print(f"Failed to notify user {username}: {e}", file=sys.stderr)
                        
                        client.delete(job.id)
                        continue
                    else:
                        print(f"Error validating post {post_id}: {e}", file=sys.stderr)
                        client.bury(job.id)
                        continue
                except Exception as e:
                    print(f"Error validating post {post_id}: {e}", file=sys.stderr)
                    client.bury(job.id)
                    continue
                
            except greenstalk.TimedOutError:
                continue
            except Exception as e:
                print(f"Error in validation worker loop: {e}", file=sys.stderr)
                continue
        
        print("Validation worker shutting down gracefully...")
        
    except KeyboardInterrupt:
        print("\nValidation worker interrupted")
    except Exception as e:
        print(f"Fatal error in validation worker: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            client.close()
        except:
            pass


def notification_worker():
    """Worker to send email notifications when posts are liked."""
    global shutdown_requested
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print(f"Starting like notification worker (Beanstalkd: {BEANSTALKD_HOST}:{BEANSTALKD_PORT})")
    
    try:
        client = greenstalk.Client((BEANSTALKD_HOST, BEANSTALKD_PORT))
        client.watch(LIKE_NOTIFICATION_QUEUE)
        client.ignore("default")
        
        print(f"Watching queue: {LIKE_NOTIFICATION_QUEUE}")
        
        while not shutdown_requested:
            try:
                job = client.reserve(timeout=1)
                
                if job is None:
                    continue
                
                try:
                    job_data = json.loads(job.body)
                    post_id = job_data["post_id"]
                    liker_username = job_data["liker_username"]
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"Invalid job data: {e}", file=sys.stderr)
                    client.delete(job.id)
                    continue
                
                # Get post information to find the author
                timelines_service_url = get_service_url_sync("timelines")
                users_service_url = get_service_url_sync("users")
                
                if not timelines_service_url or not users_service_url:
                    print(f"Services not available, burying job {job.id}", file=sys.stderr)
                    client.bury(job.id)
                    continue
                
                # Get post author - we need to find which user created the post
                # Since we don't have a direct GET /posts/{post_id}, we'll need to query
                # For this implementation, we'll get the post from public timeline
                # In production, you'd have a dedicated endpoint
                try:
                    with httpx.Client(timeout=5.0) as http_client:
                        # Get public timeline and find the post
                        resp = http_client.get(f"{timelines_service_url}/posts", params={"limit": 200})
                        if resp.status_code == 200:
                            posts = resp.json()
                            post = next((p for p in posts if p.get("post_id") == post_id), None)
                            
                            if post:
                                post_author_username = post.get("username")
                                
                                # Get post author's email
                                user_resp = http_client.get(f"{users_service_url}/users/{post_author_username}")
                                if user_resp.status_code == 200:
                                    user_data = user_resp.json()
                                    author_email = user_data.get("email")
                                    
                                    if author_email and author_email != liker_username:
                                        # Send notification email
                                        subject = "Your Post Was Liked"
                                        body = f"Hello {post_author_username},\n\n{liker_username} liked your post:\n\n{post.get('text', '')[:100]}...\n\nBest regards,\nMicroblog Team"
                                        if send_email(author_email, subject, body):
                                            print(f"Sent notification to {post_author_username} for post {post_id}")
                                        else:
                                            print(f"Failed to send notification to {post_author_username}", file=sys.stderr)
                            else:
                                print(f"Post {post_id} not found for notification", file=sys.stderr)
                except Exception as e:
                    print(f"Error sending notification for post {post_id}: {e}", file=sys.stderr)
                
                client.delete(job.id)
                
            except greenstalk.TimedOutError:
                continue
            except Exception as e:
                print(f"Error in notification worker loop: {e}", file=sys.stderr)
                continue
        
        print("Notification worker shutting down gracefully...")
        
    except KeyboardInterrupt:
        print("\nNotification worker interrupted")
    except Exception as e:
        print(f"Fatal error in notification worker: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            client.close()
        except:
            pass


def main():
    """Main entry point - runs validation worker by default."""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "notification":
        notification_worker()
    else:
        validate_post_worker()


if __name__ == "__main__":
    main()

