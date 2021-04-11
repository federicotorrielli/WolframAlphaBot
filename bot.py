import asyncio
import json
import os
import threading
import time

import amanobot
import pytesseract
import wolframalpha
from amanobot.aio.delegate import create_open, pave_event_space, per_chat_id
from amanobot.aio.loop import MessageLoop
from amanobot.helper import SafeDict
from pydub import AudioSegment
from speech_recognition import AudioFile, Recognizer, UnknownValueError

try:
    from PIL import Image
except ImportError:
    import Image

data = SafeDict()
MAX_MESSAGE_LENGTH = 4096


async def start(chat_id, name):
    welcome = f'Welcome to wolframalphaquerybot 2.2 by @evilscript, {name}, send me a query or a voice audio, like ' \
              f'1GHz to Hz or log(25)!\nUPDATE 2.2: You can send me an image and receive the text inside it!'
    await bot.sendMessage(chat_id, welcome)
    await bot.sendMessage(chat_id,
                          'You can ask me everything you have in mind, but if you need some help: '
                          'https://www.wolframalpha.com/examples/')


async def help_me(chat_id):
    await bot.sendMessage(chat_id, 'If you are here, you probably don\'t understand what\'s this bot is about.\nYou '
                                   'don\'t have to write commands to make it work, just write plain in the chat a '
                                   'query like 256*log(25) and receive the result, or do a voice audio in english '
                                   'with your query!')


async def yes_no(chat_id, its_yes):
    if chat_id in data:
        item = data.pop(chat_id)
        if its_yes and item is not None:
            for i in item:
                try:
                    await bot.sendPhoto(chat_id, i.get('@src'))
                except amanobot.exception.TelegramError:
                    # There is a gif instead of an image
                    await bot.sendVideo(chat_id, i.get('@src'))
                    pass
        else:
            await bot.sendMessage(chat_id, 'No previous message, try to say something!')
    else:
        await bot.sendMessage(chat_id, 'No previous message, try to say something!')


async def process_result(chat_id, txt):
    result = client.query(input=txt, scantimeout=10.0)
    images = []
    if hasattr(result, 'results') and result.results is not None:
        cond = False
        for p in result.pods:
            if cond:
                for subpod in p.subpods:
                    for sub in subpod.img:
                        images.append(sub)
                        if hasattr(sub, '@alt'):
                            try:
                                await bot.sendMessage(chat_id, p['@title'] + ": " + sub['@alt'])
                            except amanobot.exception.TelegramError:
                                # String is way too big to send
                                await split_and_send(chat_id, p['@title'] + ": " + sub['@alt'])
            else:
                cond = True

        data[chat_id] = images
        await bot.sendMessage(chat_id, 'Would you like to see it in images? write /yes or /no commands.')
    else:
        await bot.sendMessage(chat_id,
                              'No result found! Try writing something else, like an equation! You must '
                              'write it in english, without any emoji!')


async def process_audio(chat_id, msg):
    await bot.download_file(msg['voice']['file_id'], "./dest.ogg")
    filename = "dest.ogg"
    dest = "dest.flac"
    r = Recognizer()
    sound = AudioSegment.from_ogg(filename)
    os.unlink(filename)
    sound.export(dest, format="flac")
    with AudioFile(dest) as source:
        # listen for the data (load audio to memory)
        audio_data = r.record(source)
        # recognize (convert from speech to text)
        try:
            text = r.recognize_google(audio_data)
            print(f"VOICE LOG - {msg['from']['first_name']}: {text}")
            await process_result(chat_id, text)
        except UnknownValueError:
            await bot.sendMessage(chat_id, 'This audio is too short or corrupted, retry!')
            pass
    try:
        os.unlink(dest)
    except PermissionError:
        pass


async def process_image(chat_id, msg):
    await bot.download_file(msg['photo'][len(msg['photo']) - 1]['file_id'], "./dest.jpg")
    await bot.sendMessage(chat_id,
                          f"Result: {pytesseract.image_to_string(Image.open('./dest.jpg'), lang='eng+it+deu')}")
    print(f"IMAGE LOG: {msg['from']['first_name']}")


def load_credentials():
    """
    Loads credentials from a credentials.json file
    The .json file should have a TOKEN entry and
    a Client entry, for the Telegram API Token
    and WolframAlpha API Token
    :return: two strings, one token and one client_id
    """
    with open('credentials.json') as credentials:
        cred = json.load(credentials)
        return cred["TOKEN"], cred["Client"]


async def split_and_send(chat_id, text):
    parts = []
    while len(text) > 0:
        if len(text) > MAX_MESSAGE_LENGTH:
            part = text[:MAX_MESSAGE_LENGTH]
            first_lnbr = part.rfind('\n')
            if first_lnbr != -1:
                parts.append(part[:first_lnbr])
                text = text[first_lnbr:]
            else:
                parts.append(part)
                text = text[MAX_MESSAGE_LENGTH:]
        else:
            parts.append(text)
            break

    msg = None
    for part in parts:
        await bot.sendMessage(chat_id, part)
        time.sleep(0.5)
    return msg


def cleaner(f_stop):
    print(f'LOG: Cleaned {len(data)} items!')
    data.clear()
    if not f_stop.is_set():
        threading.Timer(5000, cleaner, [f_stop]).start()


stop = threading.Event()
cleaner(stop)


class MessageHandler(amanobot.aio.helper.ChatHandler):
    def __init__(self, *args, **kwargs):
        super(MessageHandler, self).__init__(*args, **kwargs)
        self._count = 0

    async def on_chat_message(self, msg):
        content_type, chat_type, chat_id = amanobot.glance(msg)
        if content_type == 'text':
            txt = str(msg['text'])
            name = msg['from']['first_name']
            print("LOG: " + name + ": " + txt)

            if txt == '/start':
                await start(chat_id, name)
            elif txt == '/help':
                await help_me(chat_id)
            elif txt == '/yes':
                await yes_no(chat_id, True)
            elif txt == '/no':
                await yes_no(chat_id, False)
            else:
                await process_result(chat_id, txt)
        elif content_type == 'voice':
            await process_audio(chat_id, msg)
        elif content_type == 'photo':
            await process_image(chat_id, msg)


if __name__ == '__main__':
    TOKEN, client_id = load_credentials()
    client = wolframalpha.Client(client_id)

    bot = amanobot.aio.DelegatorBot(TOKEN, [
        pave_event_space()(
            per_chat_id(), create_open, MessageHandler, timeout=20),
    ])
    bot.getUpdates(offset=-1)
    loop = asyncio.get_event_loop()
    loop.create_task(MessageLoop(bot).run_forever())
    loop.run_forever()
