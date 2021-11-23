import asyncio
import json
import os
import tempfile
import threading
import time
import zipfile

import amanobot
import pytesseract
import requests
import wolframalpha
from amanobot.aio.delegate import create_open, pave_event_space, per_chat_id
from amanobot.aio.loop import MessageLoop
from amanobot.helper import SafeDict
from PIL import Image
from pydub import AudioSegment
from speech_recognition import AudioFile, Recognizer, UnknownValueError

data = SafeDict()  # Data structure to store the messages, we use it to respond to the user when a /yes or /no command is received
MAX_MESSAGE_LENGTH = 4096 # Max message length is 4096, so we split the message in chunks of 4096


async def start(chat_id, name):
    """
    Sends a welcome message to the user
    """
    welcome = f'Welcome to WolframAlpha Bot by @evilscript, {name}, send me a query or a voice audio, like ' \
              f'1GHz to Hz or log(25)!\n---\n'\
              f'You can ask me everything you have in mind, but if you need some help: '\
              f'https://www.wolframalpha.com/examples/'
    await bot.sendMessage(chat_id, welcome)


async def help_me(chat_id):
    """
    Sends a help message to the user
    """
    await bot.sendMessage(chat_id, 'If you are here, you probably don\'t understand what\'s this bot is about.\nYou '
                                   'don\'t have to write commands to make it work, just write plain in the chat a '
                                   'query like 256*log(25) and receive the result, or do a voice audio in english '
                                   'with your query!')


def compress_file(file_urls):
    """
    Download all the files from file_urls list of URLs into a temporary directory
    then compress them into a single .zip file and return the path to the zip file
    """
    # Download the files
    files = []
    for url in file_urls:
        # Download the file and save it to a temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".gif")
        temp_file.write(requests.get(url).content)
        temp_file.close()
        files.append(temp_file.name)
    # Create a temporary zip file to store the files
    zip_file = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    # Write the files to the temporary zip file
    with zipfile.ZipFile(zip_file, "w") as zf:
        for file in files:
            zf.write(f"{file}", f"{file}")
    # Return file path
    return zip_file.name


async def yes_no(chat_id, its_yes):
    """
    Process the /yes or /no command.
    If yes, send the images to the user, if no, delete the data structure
    """
    files = []
    if chat_id in data:
        item = data.pop(chat_id)
        if its_yes and item is not None:
            for i in item:
                files.append(i.get('@src'))
            with open(compress_file(files), 'rb') as f:
                await bot.sendDocument(chat_id, f)
        else:
            await bot.sendMessage(chat_id, 'No previous message, try to say something!')
    else:
        await bot.sendMessage(chat_id, 'No previous message, try to say something!')


async def process_result(chat_id, txt):
    """
    Process the result of the query
    """
    result = client.query(input=txt, scantimeout=10.0)
    images = []
    text_result = []
    if hasattr(result, 'results') and result.results is not None:
        cond = False
        for p in result.pods:
            if cond:
                for subpod in p.subpods:
                    images.append(subpod.img)
                    if subpod.plaintext is not None:
                        text_result.append(subpod.plaintext)
            else:
                cond = True
        if len(text_result) > 0:
            await split_and_send(chat_id, "\n---\n".join(text_result))
            data[chat_id] = images
            await bot.sendMessage(chat_id, 'Would you like to see it in images? write /yes or /no commands.')
        else:
            await bot.sendMessage(chat_id, 'No result found!')
    else:
        await bot.sendMessage(chat_id,
                              'No result found! Try writing something else, like an equation! You must '
                              'write it in english, without any emoji!')


async def process_audio(chat_id, msg):
    """
    Send wolframalpha the text in the audio and get the result
    """
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
    """
    Send the user the text contained in the image
    """
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
    """
    Given a text, split it in pieces adjusted to the telegram
    maximum length and send them to the user
    """
    parts = []

    while len(text) > MAX_MESSAGE_LENGTH:
        parts.append(text[:MAX_MESSAGE_LENGTH])
        text = text[MAX_MESSAGE_LENGTH:]
    parts.append(text)

    for part in parts:
        await bot.sendMessage(chat_id, part)
        time.sleep(0.5)
    return text


def cleaner(f_stop):
    """
    Clear the data from the data dictionary
    """
    if len(data) > 0:
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


async def start_bot(this_bot):
    await this_bot.getUpdates(offset=-1)

if __name__ == '__main__':
    TOKEN, client_id = load_credentials()
    client = wolframalpha.Client(client_id)

    bot = amanobot.aio.DelegatorBot(TOKEN, [
        pave_event_space()(
            per_chat_id(), create_open, MessageHandler, timeout=20),
    ])
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot(bot))
    loop.create_task(MessageLoop(bot).run_forever())
    loop.run_forever()
