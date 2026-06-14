from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.routing import Match


class EndpointGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        allowed = False
        # Iterate over all routes in the application to see if any fully match the
        # request
        for route in request.app.routes:
            if hasattr(route, 'matches'):
                match_result, _ = route.matches(request)
                if match_result == Match.FULL:
                    allowed = True
                    break
        if not allowed:
            # If no route matches, immediately return a 404 response
            return Response('Not Found', status_code=404)
        return await call_next(request)
