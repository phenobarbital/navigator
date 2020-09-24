from typing import Any, List, Dict, Optional, Callable
from aiohttp.web import middleware
from aiohttp import web
from navigator.middlewares import check_path
import ujson as json

#TODO: Middleware Class to avoid repeat check_path($0)

@middleware
async def django_session(request, handler):
    id = None
    if not check_path(request.path):
        return await handler(request)
    try:
        id = request.headers.get('sessionid', None)
    except Exception as e:
        print(e)
        id = request.headers.get('X-Sessionid', None)
        print(id)
    if not id:
        # TODO: authorization
        return await handler(request)
    print('ID is not none')
    elif id is not None:
        print('ID is not none', id)
        session = None
        try:
            session = await request.app['session'].decode(key=id)
        except Exception as err:
            print('Error Decoding Session: {}, {}'.format(err, err.__class__))
            return await handler(request)
        if session is not None:
            try:
                request['user_id'] = session['user_id']
                request['session'] = session
            except Exception as err:
                #TODO: response to an auth error
                message = {
                    'code': 403,
                    'message': 'Invalid Session or Authentication Error',
                    'reason': str(err)
                }
                return web.json_response({'error': message})
            finally:
                return await handler(request)
