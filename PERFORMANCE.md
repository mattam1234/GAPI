# GAPI Performance & Caching Documentation

## Overview
This document describes the performance optimization strategies implemented in GAPI to ensure fast, efficient operation at scale.

## Backend Optimization (performance.py)

### 1. **In-Memory Cache Store**
- TTL-based caching with automatic expiration
- LRU eviction when max_size is reached
- Default TTL: 5 minutes (configurable)
- Cache hit/miss tracking for analytics

```python
from performance import get_cache

cache = get_cache()
cache.set('key', {'data': 'value'}, ttl=600)  # Cache for 10 mins
data = cache.get('key')
stats = cache.stats()  # Get hit rate, size, etc.
```

### 2. **Caching Decorator**
Automatically cache function results:

```python
from performance import cached

@cached(ttl=300, key_prefix='user')
def get_user_profile(user_id):
    # Only called once per 5 minutes
    return db.query(User).get(user_id)
```

### 3. **Query Pagination**
Two pagination strategies:

#### Offset-Based (Standard Pagination)
```python
from performance import Paginator

results = Paginator.paginate(
    query_result=[...],
    page=1,
    per_page=20,
    total_count=100
)
# Returns: {items, page, per_page, total, total_pages, has_prev, has_next}
```

#### Cursor-Based (Real-Time Data)
Better for fast-changing leaderboards and feeds:

```python
results = Paginator.cursor_paginate(
    items=[...],
    cursor=None,  # From previous response
    limit=20,
    cursor_field='id'
)
# Returns: {items, cursor, next_cursor, has_more}
```

### 4. **Query Optimization**
Built-in helpers to prevent N+1 queries:

```python
from performance import QueryOptimizer

# Batch select (instead of loop + individual queries)
users = QueryOptimizer.batch_select(db_session, User, user_ids)
# Returns: {user_id: User}

# Count distinct
count = QueryOptimizer.count_distinct(db_session, User, User.email)
```

### 5. **Index Analysis**
Get automated database index suggestions:

```python
from performance import IndexAnalyzer

suggestions = IndexAnalyzer.analyze_query_bottlenecks()
# Returns: List of SQL CREATE INDEX statements
```

### 6. **Performance Monitoring**
Track endpoint performance:

```python
from performance import get_monitor

monitor = get_monitor()
monitor.start_timer('fetch_users')
# ... do work ...
elapsed = monitor.end_timer('fetch_users')

stats = monitor.get_stats('fetch_users')
# Returns: {count, min, max, avg, total} in milliseconds
```

### 7. **Response Optimization**
Reduce response payload size:

```python
from performance import ResponseOptimizer

# Compress JSON
compact = ResponseOptimizer.compress_json(data)

# Return only requested fields
filtered = ResponseOptimizer.partial_response(data, ['id', 'username'])

# Generate ETag for client-side caching
etag = ResponseOptimizer.add_etag(data)
```

## New API Endpoints for Optimization

### Cache Management
**GET /api/system/cache/stats**
- Get cache hit rate and performance metrics
- Returns: `{cache: {size, max_size, hits, misses, hit_rate}, performance: {...}}`

**POST /api/system/cache/clear**
- Clear all server-side cache (admin only)

**GET /api/system/indexes**
- Get database index optimization suggestions
- Returns: Array of SQL CREATE INDEX statements

### Optimized List Endpoints
All list endpoints support pagination with these parameters:
- `page`: Current page (default: 1)
- `per_page`: Results per page (default: 20, max: 100)

**GET /api/optimized/users**
- Paginated user list

**GET /api/optimized/games**
- Paginated game library

**GET /api/optimized/leaderboard**
- Cached leaderboard with pagination
- 10-minute cache TTL
- Parameters: `category` (picks, acceptance, votes, accuracy)

**GET /api/optimized/chat/messages**
- Paginated chat messages per room
- Parameters: `room` (default: general)

**GET /api/optimized/games/search**
- Game search with pagination
- Parameters: `q` (search query)

## Frontend Optimization (frontend-optimization.js)

### 1. **Frontend Cache**
Client-side caching of API responses:

```javascript
const frontendCache = new FrontendCache({
    maxSize: 100,        // Cache up to 100 entries
    defaultTTL: 300000   // 5 minute TTL
});

// Set data
frontendCache.set('leaderboard:picks', data, 600000);  // 10 min TTL

// Get data (auto-expires)
const data = frontendCache.get('leaderboard:picks');

// Stats
console.log(frontendCache.stats());
```

### 2. **Pagination UI**
Automatic pagination controls:

```javascript
// Render page selector
const htmlPageSelector = PaginationHelper.createPageSelector(
    totalPages=10,
    currentPage=1,
    onPageChange='changePage'
);

// Render per-page selector  
const htmlPerPageSelector = PaginationHelper.createPerPageSelector(
    onPerPageChange='changePerPage'
);
```

### 3. **Lazy Loading**
Load more data as user scrolls:

```javascript
const lazyLoader = new LazyLoader(
    container=document.getElementById('items-list'),
    loadMoreThreshold=200  // 200px from bottom
);

lazyLoader.onNearBottom(() => {
    loadNextPage();
});

lazyLoader.setHasMore(hasMorePages);
lazyLoader.setLoading(isLoading);
```

### 4. **Paginated Data Loading**
Simplified pagination with caching:

```javascript
// Load page 2, 20 items per page
const data = await loadPagedData(
    endpoint='/api/optimized/leaderboard',
    page=2,
    perPage=20
);
// {items, page, per_page, total, total_pages, ...}

// Render with pagination UI
await loadWithPagination(
    endpoint='/api/optimized/users',
    containerId='users-list'
);
```

### 5. **Frontend Performance Monitoring**
Track client-side performance:

```javascript
const frontendMonitor = new PerformanceMonitor();

frontendMonitor.startTimer('render_users');
// ... render UI ...
frontendMonitor.endTimer('render_users');

// Get stats
const stats = frontendMonitor.getStats('render_users');
// {count, min, max, avg, last} in milliseconds

// Show all stats
frontendMonitor.displayStats('stats-container');
```

### Performance Dashboard
Click the **⚡ Perf** button (bottom-right) to view:
- Server cache statistics (hits, miss rate)
- Client cache size
- Operation timing data (min/max/avg)

## Database Index Suggestions

The system suggests indexes for:
- User lookups by username/email
- Game queries by Steam ID/APP ID
- Activity tracking by user and date
- Social features (friends, follows)
- Leaderboard queries
- Chat messages by room and time
- All Phase 6 & 7 feature tables

Run `/api/system/indexes` to get the complete list of recommended `CREATE INDEX` statements.

## Caching Strategy by Feature

| Feature | Cache TTL | Strategy | Endpoint |
|---------|-----------|----------|----------|
| Leaderboards | 10 min | Full cache | `/api/optimized/leaderboard` |
| User profiles | 5 min | Function cache | `/api/users/{id}/profile` |
| Game library | Variable | Client-side | `/api/optimized/games` |
| Chat messages | No cache | Pagination | `/api/optimized/chat/messages` |
| Search results | No cache | Pagination | `/api/optimized/games/search` |
| Team info | 5 min | Function cache | `/api/teams` |
| Rankings | 10 min | Full cache | `/api/ranked` |

## Best Practices

### Backend
1. **Use pagination for list endpoints** - Default 20 items per page, max 100
2. **Cache frequently accessed data** - Leaderboards, team info, rankings
3. **Batch database queries** - Use `QueryOptimizer.batch_select()` to avoid N+1
4. **Monitor performance** - Check `/api/system/cache/stats` regularly
5. **Run index analysis** - Execute suggested indexes from `/api/system/indexes`

### Frontend
1. **Use paginated endpoints** - `/api/optimized/*` instead of `/api/*`
2. **Enable lazy loading** - For long lists, load on scroll
3. **Cache API responses** - 5-minute TTL for stable data
4. **Monitor performance** - View stats with ⚡ Perf button
5. **Compress images** - Especially for cosmetics and user avatars

### Database
1. **Add recommended indexes** - From `/api/system/indexes`
2. **Analyze query patterns** - Check slow query logs
3. **Use DISTINCT sparingly** - Group by is faster for aggregates
4. **Partition large tables** - Consider for millions of rows
5. **Update statistics** - ANALYZE tables after bulk operations

## Performance Targets

- **Leaderboard load**: < 100ms (cached)
- **User list load**: < 200ms (paginated, 20 items)
- **Search results**: < 300ms (client-side search + pagination)
- **Chat messages**: < 150ms (paginated, 20 messages)
- **Cache hit rate target**: > 70%

## Troubleshooting

### High miss rate?
- Increase TTL for stable data
- Check if cache key is consistent
- Monitor with `/api/system/cache/stats`

### Slow queries?
- Run `/api/system/indexes` and add suggested indexes
- Use paginated endpoints
- Check database slow query log

### High memory usage?
- Reduce cache max_size
- Lower TTL for less-critical data
- Clear cache periodically

## Future Improvements

1. Redis integration for distributed caching
2. Database query result pagination (keyset/seek approach)
3. Client-side IndexedDB for offline support
4. Image lazy-loading and responsive images
5. GraphQL for field-level query optimization
6. Database connection pooling optimization
7. API response compression (gzip)
