from aiohttp import web
from aiohttp.web_exceptions import HTTPError
from datamodel import BaseModel, Field
from navigator import Application
from navigator.responses import JSONResponse
from navigator.views import BaseHandler
from app import Main

class Animal(BaseModel):
    name: str = Field(required=True)
    specie: str
    age: int

class AnimalHandler(BaseHandler):
    async def save_animal(self, request: web.Request) -> web.Response:
        try:
            animal = await self.validate_handler(request=request, model=Animal, strict=True)
            if isinstance(animal, HTTPError):
                return animal
            elif isinstance(animal, BaseException):
                # return an exception:
                return web.HTTPBadRequest(
                    reason=str(animal),
                    content_type='application/json'
                )
            print(f"My Favourite Animal is: {animal}")
            # can we work directly with the model:
            return JSONResponse(animal)
        except Exception as err:
            print(err)

# define a new Application
app = Application(app=Main)

a = AnimalHandler()
app.router.add_post(
    "/api/v2/animal", a.save_animal
)

# Using the Application Context
@app.post('/api/v1/animal')
@app.validate(Animal)
def handler(request: web.Request, animal: Animal, **kwargs) -> web.Response:
    print('REQ: ', request, 'Model: ', animal, 'ARGS: ', kwargs)
    print(f"My Favourite Animal is: {animal}")
    return JSONResponse(animal)

if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
