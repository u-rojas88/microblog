# Microblog

A microservices-based microblogging platform built with FastAPI.

## Architecture

This project consists of multiple microservices that work together to provide a complete microblogging platform:

- **API Gateway**: Single entry point for all client requests
- **Service Registry**: Service discovery and health monitoring
- **Users Service**: User management, authentication, and following
- **Timelines Service**: Post creation and timeline management
- **Likes Service**: Like/unlike functionality for posts
- **Polls Service**: Poll creation and voting

## Services

### API Gateway

The API Gateway acts as a single entry point for all client requests and routes them to the appropriate backend service.

**Default Port**: 8080 (configurable via `PORT`)

**Endpoints**:
- `GET /` - API information and service status
- `GET /health` - Health check
- `GET /docs` - API documentation (Swagger UI)
- All endpoints from backend services are proxied through the gateway

### Service Registry

Manages service discovery and health monitoring. Services register themselves on startup and send periodic heartbeats.

**Default Port**: 8006 (configurable via `PORT`)

**Endpoints**:
- `GET /` - Registry information
- `GET /health` - Health check
- `GET /status` - Overall registry status
- `GET /services` - List all registered services
- `GET /services/{service_name}` - Get instances of a specific service
- `POST /register` - Register a service instance
- `POST /heartbeat/{instance_id}` - Send heartbeat
- `DELETE /deregister/{instance_id}` - Deregister a service instance

### Users Service

Handles user registration, authentication, profile management, and following relationships.

**Default Port**: 5100 (configurable via `PORT`)

**Endpoints**:
- `POST /register` - Register a new user
- `POST /login` - Authenticate and get access token
- `GET /users/{username}` - Get user profile
- `POST /users/follow/{username}` - Follow a user (requires authentication)
- `POST /users/unfollow/{username}` - Unfollow a user (requires authentication)
- `GET /users/{username}/followees` - Get list of users that a user follows

**Database**: PostgreSQL

### Timelines Service

Manages posts and provides different timeline views (user timeline, home timeline, public timeline).

**Default Port**: 5200 (configurable via `PORT`)

**Endpoints**:
- `POST /posts` - Create a new post (requires authentication)
- `POST /posts/async` - Create a post asynchronously via queue (requires authentication)
- `GET /posts/id/{post_id}` - Get a specific post by ID
- `GET /posts/{username}` - Get user timeline (posts by a specific user)
- `GET /posts` - Get public timeline (all posts)
- `GET /posts/home/{username}` - Get home timeline (posts from followed users, requires authentication)

**Database**: PostgreSQL  
**Queue**: Beanstalkd (for async post creation)

### Likes Service

Manages likes and unlikes for posts, tracks like counts, and provides popular posts.

**Default Port**: 8004 (configurable via `PORT`)

**Endpoints**:
- `POST /likes/{post_id}` - Like a post (requires authentication)
- `DELETE /likes/{post_id}` - Unlike a post (requires authentication)
- `GET /likes/{post_id}/count` - Get like count for a post
- `GET /users/{username}/likes` - Get all posts liked by a user
- `GET /likes/popular` - Get popular posts (by like count)

**Storage**: Redis  
**Queue**: Beanstalkd (for validation and notifications)

### Polls Service

Handles poll creation and voting functionality.

**Default Port**: 8005 (configurable via `PORT`)

**Endpoints**:
- `POST /polls` - Create a new poll (requires authentication)
- `GET /polls/{poll_id}` - Get poll details
- `POST /polls/{poll_id}/vote` - Vote on a poll (requires authentication)
- `GET /polls/{poll_id}/results` - Get poll results

**Database**: DynamoDB

## Environment Variables

### Common Variables

These variables are used by multiple services:

- `PORT` - Port number for the service (defaults vary by service)
- `REGISTRY_URL` - URL of the service registry (default: `http://localhost:8006`)
- `JWT_SECRET` - Secret key for JWT token signing (default: `dev-secret-change-me`)
- `JWT_ALG` - JWT algorithm (default: `HS256`)
- `JWT_EXPIRES_MINUTES` - JWT token expiration time in minutes (default: `60`)

### Database Configuration

#### PostgreSQL (Users & Timelines Services)

- `DB_HOST` - PostgreSQL host (default: `localhost`)
- `DB_PORT` - PostgreSQL port (default: `5432`)
- `DB_USER` - PostgreSQL username (default: `postgres`)
- `DB_PASSWORD` - PostgreSQL password (default: `postgres`)
- `USERS_DB_NAME` - Database name for users service (default: `microblog_users`)
- `TIMELINES_DB_NAME` - Database name for timelines service (default: `microblog_timelines`)
- `USERS_DATABASE_URL` - Full database URL for users service (overrides individual components)
- `TIMELINES_DATABASE_URL` - Full database URL for timelines service (overrides individual components)

#### Redis (Likes Service)

- `REDIS_URL` - Redis connection URL (default: `redis://127.0.0.1:6379/0`)

#### DynamoDB (Polls Service)

- `DYNAMODB_URL` - DynamoDB endpoint URL (e.g., `http://127.0.0.1:8000` for local)
- `AWS_REGION` - AWS region (default: `us-east-1`)
- `AWS_ACCESS_KEY_ID` - AWS access key (default: `dummy` for local)
- `AWS_SECRET_ACCESS_KEY` - AWS secret key (default: `dummy` for local)
- `DYNAMODB_POLLS_TABLE` - DynamoDB table name for polls (default: `Polls`)

### Queue Configuration

#### Beanstalkd (Timelines & Likes Services)

- `BEANSTALKD_HOST` - Beanstalkd host (default: `127.0.0.1`)
- `BEANSTALKD_PORT` - Beanstalkd port (default: `11300`)

### Email Configuration (Likes Notification Worker)

- `SMTP_HOST` - SMTP server host (default: `localhost`)
- `SMTP_PORT` - SMTP server port (default: `25`)

## Service Ports

Default ports for each service:

- **Gateway**: 8080
- **Registry**: 8006
- **Users**: 5100
- **Timelines**: 5200
- **Likes**: 8004
- **Polls**: 8005

## Dependencies

### External Services Required

1. **PostgreSQL** - For users and timelines services
2. **Redis** - For likes service
3. **DynamoDB** - For polls service (can use DynamoDB Local for development)
4. **Beanstalkd** - For job queues (async post creation, like validation, notifications)

### Python Dependencies

See `requirements.txt` for the complete list. Main dependencies include:
- FastAPI
- SQLAlchemy
- Redis
- Boto3 (for DynamoDB)
- Greenstalk (for Beanstalkd)
- python-jose (for JWT)
- passlib (for password hashing)

## Running the Services

Services can be started individually or using a process manager like `foreman` with the `Procfile`.

Example using environment variables:

```bash
# Start registry service
PORT=8006 python -m registry_service.app

# Start users service
PORT=5100 DB_HOST=localhost DB_USER=postgres DB_PASSWORD=postgres python -m users_service.app

# Start timelines service
PORT=5200 DB_HOST=localhost DB_USER=postgres DB_PASSWORD=postgres python -m timelines_service.app

# Start likes service
PORT=8004 REDIS_URL=redis://localhost:6379/0 python -m likes_service.app

# Start polls service
PORT=8005 DYNAMODB_URL=http://localhost:8000 python -m polls_service.app

# Start gateway
PORT=8080 REGISTRY_URL=http://localhost:8006 python gateway.py
```

## Workers

Background workers process async jobs:

- **timelines_worker**: Processes async post creation jobs
- **likes_validation_worker**: Validates that liked posts exist
- **likes_notification_worker**: Sends notifications when posts are liked

Workers can be started with:

```bash
python -m timelines_service.workers
python -m likes_service.workers
python -m likes_service.workers notification
```

## Authentication

Most endpoints require authentication via JWT Bearer tokens. To authenticate:

1. Register a user: `POST /register`
2. Login: `POST /login` (returns access token)
3. Include token in requests: `Authorization: Bearer <token>`

## API Documentation

Once services are running, interactive API documentation is available at:
- Gateway: `http://localhost:8080/docs`
- Individual services: `http://localhost:<PORT>/docs`

