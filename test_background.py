import asyncio
from aiohttp import web
from navigator import Application
from navigator.background import BackgroundTask
from app import Main

# define a new Application
app = Application(Main, enable_jinja2=True)

async def send_email(email, message):
    # Simulate email sending
    await asyncio.sleep(10)
    print(f"Email sent to {email} with message: {message}")


# Using the Application Context
@app.post('/sample_background')
async def handler(request: web.Request) -> web.Response:
    data = await request.json()
    email = data.get('email')
    message = data.get('message')

    # Create a BackgroundTask
    background_task = BackgroundTask(send_email, email, message)

    # Schedule the background task to run
    asyncio.create_task(background_task.run())

    return web.Response(text="Background task scheduled")




if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
