#!/usr/bin/python3
"""
Available models
  Akash: https://chatapi.akash.network/documentation
  Perplexity: https://docs.perplexity.ai/guides/model-cards
"""
import asyncio
import hashlib
import os
import re
import tempfile

import yt_dlp
import discord
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam
from typing import cast
import palpersonalities

# Load environment variables
discord_token = os.getenv('DISCORD_TOKEN', 'not_set')
openai_api_key = os.getenv('OPENAI_API_KEY', 'not_set')
openai_base_url = os.getenv('OPENAI_BASE_URL', 'not_set')
openai_model = os.getenv('OPENAI_MODEL', 'not_set')
# Alternate API Endpoints
akash_api_key = os.getenv('AKASH_API_KEY', 'not_set')
akash_base_url = os.getenv('AKASH_BASE_URL', 'not_set')
akash_model = os.getenv('AKASH_MODEL', 'not_set')

# Set up Discord client
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
discord_client = discord.Client(intents=intents)
print(f'DEBUG discord_client: {discord_client}', flush=True)

# Set up OpenAI client
openai_client = AsyncOpenAI(api_key=openai_api_key, base_url=openai_base_url)
akash_client = AsyncOpenAI(api_key=akash_api_key, base_url=akash_base_url)
print(f'DEBUG openai_client: {openai_client}', flush=True)
print(f'DEBUG akash_client: {akash_client}', flush=True)

# Channel settings
channel_settings = {
    'default': {
        'openai_base_url': openai_base_url,
        'openai_model': openai_model,
        'system_prompt': 'default',
    },
    'general': {
        'openai_base_url': openai_base_url,
        'openai_model': openai_base_url,
        'system_prompt': 'default',
    },
    'pal-akash-deepseek': {
        'openai_base_url': akash_base_url,
        'openai_model': 'DeepSeek-V3-1',
        'system_prompt': 'default',
    },
    'pal-akash-llama': {
        'openai_base_url': akash_base_url,
        'openai_model': 'Meta-Llama-4-Maverick-17B-128E-Instruct-FP8',
        'system_prompt': 'default',
    },
    'pal-online': {
        'openai_base_url': openai_base_url,
        'openai_model': 'sonar-pro',
        'system_prompt': 'online',
    },
    'pal-offline': {
        'openai_base_url': openai_base_url,
        'openai_model': 'sonar',
        'system_prompt': 'default',
    },
}

system_prompt_dict = {
    'default': palpersonalities.default,
    'conservative': palpersonalities.conservative,
    'liberal': palpersonalities.liberal,
    'online': palpersonalities.online,
    'neutral': palpersonalities.neutral,
}


def format_audio_file(string):
    string = string.replace(' ', '_').replace('$', '').lower()
    string = string.replace('(', '').replace(')', '')
    string = string.replace('{', '').replace('}', '')
    string = string.replace('[', '').replace(']', '')
    string = string.replace('.', '').replace(',', '')
    string = string.replace('\\', '').replace("'", '').replace('"', '').replace('|', '')
    return string


async def generate_system_prompt_metadata(event):
    """
    Take the event dictionary we are passed and generate a system-prompt header for this event.
    """
    channel_name = event.get('channel_name')
    server_name = event.get('server_name')
    system_prompt = '# Begin Context: Discord Metadata'
    system_prompt += f'\nChannel: {channel_name}\nServer: {server_name}'
    if bool(event.get('is_bot', False)):
        system_prompt += '\nYou are communicating with another bot.'
    else:
        user_name = event.get('user_name')
        system_prompt += f'\nYou are communicating with {user_name}'

    system_prompt += '\n# End Context: Discord Metadata'
    return system_prompt


async def handle_message(event):
    channel_base_url = event.get('channel_base_url', '')
    channel_model = event.get('channel_model', '')
    channel_prompt = event.get('channel_prompt', '')
    message_text = event.get('message', '')
    system_prompt_footer = event.get('channel_context', '')
    channel_history = event.get('channel_history', '')
    use_akash = bool('akash' in channel_base_url)
    if use_akash:
        selected_client = akash_client
    else:
        selected_client = openai_client

    try:
        messages = [
            {'role': 'system', 'content': channel_prompt + system_prompt_footer},
            {'role': 'user', 'content': message_text + channel_history},
        ]
        response = await selected_client.chat.completions.create(
            model=channel_model,
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
        )
        # print(f'DEBUG Client response: {response}')
        result = response.choices[0].message.content
        is_deepseek = bool('deepseek' in response.model)
        is_reasoning_requested = bool('+reasoning' in message_text.lower())
        if is_deepseek or not is_reasoning_requested:
            print('DEBUG Removing <think></think> tags', flush=True)
            result = await remove_think_tags(result)

        is_refusal = bool(response.choices[0].message.refusal)
        if is_refusal:
            print(f'DEBUG Model has refused to answer this prompt: {response.choices[0].message.refusal}', flush=True)
        try:
            citations = response.citations
        except:
            citations = []

        usage = response.usage
        print(f'openai response (length: {len(result)}):\n{result}', flush=True)
        print(f'DEBUG usage:\n{usage}', flush=True)
        print(f'DEBUG citations:\n{citations}', flush=True)
        citation_text = 'Citations:\n'
        citation_count = 1
        for citation in citations[:3]:
            citation_text += f'> [{citation_count}] {citation}\n'
            citation_count += 1

        return result, citation_text

    except Exception as err:
        print(f'error: {err}', flush=True)
        return '', []


async def provide_judgement(event):
    message_text = event.get('message', '')
    channel_model = event.get('channel_model', '')
    judges = [
        {
            'prompt': palpersonalities.conservative,
            'openai_base_url': akash_base_url,
            'openai_model': 'nvidia-Llama-3-1-Nemotron-70B-Instruct-HF',
            'temperature': 0.3,
        },
        {
            'prompt': palpersonalities.liberal,
            'openai_base_url': akash_base_url,
            'openai_model': 'Meta-Llama-3-2-3B-Instruct',
            'temperature': 0.7
        },
    ]
    final_judge = {
        'prompt': palpersonalities.neutral,
        'openai_base_url': akash_base_url,
        'openai_model': 'Meta-Llama-3-3-70B-Instruct',
        'temperature': 0.5,
    }
    judgements = []
    if message_text:
        try:
            for judge in judges:
                print('Judging...', flush=True)
                use_akash = bool('akash' in judge['openai_base_url'])
                if use_akash:
                    selected_client = akash_client
                else:
                    selected_client = openai_client

                judge_messages = [
                    {'role': 'system', 'content': judge['prompt']},
                    {'role': 'user', 'content': message_text},
                ]
                response = await selected_client.chat.completions.create(
                    model=judge['openai_model'],
                    messages=judge_messages,
                    max_tokens=512,
                    temperature=judge['temperature'],
                )

                result = response.choices[0].message.content
                print(f'judgement response: {result}', flush=True)
                judgements.append(result)

        except Exception as err:
            print(f'error: {err}', flush=True)
            return ''

        # Combine judgements
        judgement_context = '# Purpose\nAnalyze the judgement statement and the provided judgements below. Formulate a final judgement.\n'
        judgement_context += f'# Judgement Statement\n{message_text}\n'
        for context in judgements:
            judgement_context += '# Judgement Provided\n'
            judgement_context += context + '\n'

        try:
            print(f'\nJudgement Context:\n{judgement_context}\n', flush=True)
            use_akash = bool('akash' in final_judge['openai_base_url'])
            if use_akash:
                selected_client = akash_client
            else:
                selected_client = openai_client

            final_messages = [
                cast(ChatCompletionSystemMessageParam,
                     cast(object, {'role': 'system', 'content': final_judge['prompt']})),
                cast(ChatCompletionUserMessageParam, cast(object, {'role': 'user', 'content': judgement_context})),
            ]
            judgement_response = await selected_client.chat.completions.create(
                model=final_judge['openai_model'],
                messages=final_messages,
                max_tokens=512,
                temperature=final_judge['temperature'],
            )

            judgement_result = judgement_response.choices[0].message.content
            print(f'\nfinal response:\n{judgement_result}\n', flush=True)
            return judgement_result

        except Exception as err:
            print(f'error: {err}', flush=True)
            return ''


async def get_channel_messages(event, limit=10):
    channel_obj = discord_client.get_channel(event.get('channel_id'))
    response = '# Begin Context: Channel Message History\n'
    async for msg in channel_obj.history(limit=limit):
        if msg.author == event.get('is_me', ''):
            response += f'{msg.author}: [AI GENERATED CONTENT]\n'
        else:
            response += f'{msg.author}: {msg.content}\n'

    response += '# End Context: Channel Message History\n'
    print(f'\n{response}', flush=True)
    return response


async def send_message(msg_obj, msg_txt):
    if msg_txt:
        print('Sending message...', flush=True)
        # Split the message into chunks of 2000 characters
        for i in range(0, len(msg_txt), 2000):
            chunk = msg_txt[i:i + 2000]
            try:
                await msg_obj.channel.send(chunk)
            except Exception as err:
                print(f'Error sending message: {err}')


async def remove_think_tags(text):
    """
    DeepSeek includes the reasoning output in <think></think> tags and we need to remove this for chat responses.
    """
    pattern = r'<think>.*?</think>'
    return re.sub(pattern, '', text, flags=re.DOTALL)


def is_youtube_url(text):
    """
    Check if the message contains a YouTube URL.
    """
    youtube_pattern = r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})'
    return bool(re.search(youtube_pattern, text))


async def download_youtube_as_audio_only(url, start_quality='192'):
    """
    Download YouTube video and convert to audio file.
    Returns the path to the audio file or None if failed.
    """
    print(f'Starting YouTube download for URL: {url}', flush=True)
    qualities = ['192', '128'] if start_quality == '192' else ['128', '192']
    for quality in qualities:
        try:
            # Create temporary directory for download
            with tempfile.TemporaryDirectory() as temp_dir:
                random_bytes = os.urandom(32)
                hash_value = hashlib.sha256(random_bytes).hexdigest()
                output_path = os.path.join(temp_dir, hash_value)
                # yt-dlp options for audio file conversion
                ydl_ext = 'm4a'
                ydl_opts = {
                    'format': 'm4a/bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': ydl_ext,
                        'preferredquality': quality,
                    }],
                    'outtmpl': output_path,
                    'quiet': False,
                    'no_warnings': True,
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # Extract info first to get title
                    print(f'Extracting video info for quality {quality}...', flush=True)
                    info = ydl.extract_info(url, download=False)
                    title = info.get('title', 'unknown')
                    print(f'Video title: {title}', flush=True)
                    # Download and convert
                    print(f'Downloading and converting with quality {quality}...', flush=True)
                    ydl.download([url])
                    print(f'Download and conversion completed for quality {quality}', flush=True)
                    print(f'Temporary path: {output_path}', flush=True)
                    extracted_audio_path = output_path + f'.{ydl_ext}'
                    if os.path.exists(extracted_audio_path):
                        # Check file size (Discord limit is 10MB)
                        file_size = os.path.getsize(extracted_audio_path)
                        print(f'Generated file size: {file_size} bytes', flush=True)
                        if file_size > 10 * 1024 * 1024:  # 10MB
                            print(f'File too large ({file_size} bytes > 10MB), trying next quality', flush=True)
                            continue  # Try next quality

                        # Move to a persistent location for upload
                        title = format_audio_file(title)
                        final_path = f'/tmp/{title}.{ydl_ext}'
                        print(f'Moving audio file to: {final_path}', flush=True)
                        os.rename(extracted_audio_path, final_path)
                        return final_path
                    else:
                        print(f'Failed to locate download: {extracted_audio_path}', flush=True)

            return None

        except Exception as err:
            print(f'Error downloading/converting YouTube video with quality {quality}: {err}', flush=True)
            print(f'Failed URL: {url}', flush=True)
            continue  # Try next quality

    print(f'All quality attempts failed for URL: {url}', flush=True)
    return None


@discord_client.event
async def on_ready():
    print(f'{discord_client.user} has connected to Discord!', flush=True)

    return

@discord_client.event
async def on_message(message):
    event = {}
    if message.author == discord_client.user:
        # Loop avoidance.
        print('Ignoring a message from myself.', flush=True)
        return

    try:
        print(f'received: {message.content}', flush=True)
        print(f'channel: {message.channel.name} [{message.channel.id}]', flush=True)
        print(f'author: {message.author.name} [{message.author.id} bot:{message.author.bot}]', flush=True)
        print(f'server: {message.guild.name} [{message.guild.id}]', flush=True)
        channel_defaults = channel_settings['default']
        channel_prompt_name = channel_settings.get(message.channel.name, channel_defaults).get('system_prompt')
        event = {
            'channel_name': message.channel.name,
            'channel_id': message.channel.id,
            'channel_prompt': system_prompt_dict.get(channel_prompt_name, ''),
            'channel_model': channel_settings.get(message.channel.name, channel_defaults).get('openai_model'),
            'channel_base_url': channel_settings.get(message.channel.name, channel_defaults).get('openai_base_url'),
            'user_id': message.author.id,
            'user_name': message.author.name,
            'is_bot': bool(message.author.bot),
            'is_me': discord_client.user,
            'server_name': message.guild.name,
            'message': message.content,
        }
        message_history = await get_channel_messages(event)
        event.update({'channel_history': message_history})
        channel_context = await generate_system_prompt_metadata(event)
        event.update({'channel_context': channel_context})
    except Exception as err:
        print(f'Unable to setup event dictionary: {err}', flush=True)

    # Handle YouTube links
    yt_conditions = [
        bool(message.channel.name == 'music'),
        bool(message.content.startswith('get ') or message.content.startswith('!get')),
        bool(is_youtube_url(message.content)),
    ]
    if all(yt_conditions):
        await message.add_reaction('🎵')
        print('Processing YouTube link...\n', flush=True)

        # Extract YouTube URL from message
        yt_match_pattern = r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})'
        youtube_urls = re.findall(yt_match_pattern, message.content)
        if youtube_urls:
            youtube_url = f'https://youtu.be/{youtube_urls[0]}'
            audio_file_path = await download_youtube_as_audio_only(youtube_url)

            if audio_file_path:
                try:
                    await message.channel.send(file=discord.File(audio_file_path))
                    print(f'Successfully uploaded audio file: {audio_file_path}', flush=True)
                except Exception as err:
                    print(f'Error uploading audio file with initial quality: {err}', flush=True)
                    # Retry with lower quality (128)
                    audio_file_path2 = await download_youtube_as_audio_only(youtube_url, start_quality='128')
                    if audio_file_path2:
                        try:
                            await message.channel.send(file=discord.File(audio_file_path2))
                            print(f'Successfully uploaded audio file on retry: {audio_file_path2}', flush=True)
                        except Exception as err2:
                            print(f'Error uploading audio file on retry: {err2}', flush=True)
                            await message.channel.send('Sorry, there was an error uploading the audio file file.')
                        finally:
                            try:
                                os.remove(audio_file_path2)
                            except:
                                pass
                    else:
                        await message.channel.send('Sorry, I couldn\'t convert that YouTube video to audio file. It might be too long or unavailable.')
                finally:
                    try:
                        os.remove(audio_file_path)
                    except:
                        pass
            else:
                await message.channel.send('Sorry, I couldn\'t convert that YouTube video to audio file. It might be too long or unavailable.')

        return

    if message.content.startswith('guidance:') or message.content.startswith('!guidance'):
        await message.add_reaction('👍')
        print('Awaiting guidance...\n', flush=True)
        judgement_response = await provide_judgement(event)
        await send_message(message, judgement_response)
        return

    if message.content.startswith('online:') or message.content.startswith('!online'):
        await message.add_reaction('👍')
        print('Searching the interwebs...\n', flush=True)
        event.update({'channel_model': 'sonar-pro'})
        if not '+history' in message.content:
            event.update({'channel_history': ''})

        response, citations = await handle_message(event)
        await send_message(message, response)
        if citations and '+citations' in message.content:
            await send_message(message, citations)

        return

    if message.content.startswith('hey pal') or message.channel.name.startswith('pal-'):
        await message.add_reaction('👍')
        print('Handling message...\n', flush=True)
        if not '+history' in message.content:
            event.update({'channel_history': ''})

        response, citations = await handle_message(event)
        await send_message(message, response)
        if citations and '+citations' in message.content:
            await send_message(message, citations)

        return


if __name__ == '__main__':
    async def main():
        # Run the Discord client
        await discord_client.start(discord_token)

    # Use asyncio.run to create a new event loop
    asyncio.run(main())
