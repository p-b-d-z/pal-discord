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
import time

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
    'utilitarian': palpersonalities.utilitarian,
    'legal_expert': palpersonalities.legal_expert,
    'medical_expert': palpersonalities.medical_expert,
    'environmental_expert': palpersonalities.environmental_expert,
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


def format_response(response: str) -> str:
    """
    Clean up AI response formatting to ensure Slack compatibility using regex patterns
    """
    if not response:
        return response

    # Remove common AI starting phrases
    response = re.sub(r'^(Sure|Certainly|Got it),?\s+', '', response, flags=re.IGNORECASE)

    # Replace bold Markdown formatting, preserving the text between markers
    bold_pattern = r'\*\*(.+?)\*\*'
    response = re.sub(bold_pattern, r'*\1*', response)

    # Fix code block formatting, ensuring newlines around the content
    bash_pattern = r'```bash\n'
    response = re.sub(bash_pattern, r'```\n#!/bin/bash\n', response, flags=re.DOTALL)
    python_pattern = r'```python\n'
    response = re.sub(python_pattern, r'```\n#!/usr/bin/python3\n', response, flags=re.DOTALL)
    other_pattern = r'```\w\n'
    response = re.sub(other_pattern, r'```\n', response, flags=re.DOTALL)
    # Catch all for code blocks
    code_pattern = r'```(.*?)```'
    response = re.sub(code_pattern, r'```\n\1\n```\n', response, flags=re.DOTALL)

    # Fix URL formatting [text](url) -> <url|text>
    url_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    response = re.sub(url_pattern, r'<\2|\1>', response)

    # Replace double line breaks with single line breaks
    lb_pattern = r'\n\n'
    response = re.sub(lb_pattern, r'\n', response, flags=re.DOTALL)

    # Remove think tags
    pattern = r'<think>.*?</think>'
    response = re.sub(pattern, r'', response, flags=re.DOTALL)

    return response.strip()


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
            messages=messages,  # noqa
            max_tokens=1024,
            temperature=0.7,
        )
        # print(f'DEBUG Client response: {response}')
        result = response.choices[0].message.content
        result = format_response(result)
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


# Global judgement cache
judgement_cache = {}

def get_cache_key(message_text):
    return hashlib.md5(message_text.encode()).hexdigest()

async def check_judgement_cache(message_text):
    key = get_cache_key(message_text)
    if key in judgement_cache:
        cache_entry = judgement_cache[key]
        if time.time() - cache_entry['timestamp'] < 3600:  # 1 hour
            return cache_entry['result']
    return None

def select_expert_judges(message_text):
    judges = [
        {
            'name': 'conservative',
            'prompt': palpersonalities.conservative,
            'openai_base_url': akash_base_url,
            'openai_model': 'DeepSeek-R1-Distill-Qwen-32B',
            'temperature': 0.3,
        },
        {
            'name': 'liberal',
            'prompt': palpersonalities.liberal,
            'openai_base_url': akash_base_url,
            'openai_model': 'Meta-Llama-3-3-70B-Instruct',
            'temperature': 0.7
        },
        {
            'name': 'utilitarian',
            'prompt': palpersonalities.utilitarian,
            'openai_base_url': akash_base_url,
            'openai_model': 'Meta-Llama-4-Maverick-17B-128E-Instruct-FP8',
            'temperature': 0.5,
        },
    ]

    # Add expert judges based on content
    if 'legal' in message_text.lower() or 'law' in message_text.lower() or 'court' in message_text.lower():
        judges.append({
            'name': 'legal_expert',
            'prompt': palpersonalities.legal_expert,
            'openai_base_url': akash_base_url,
            'openai_model': 'Qwen3-235B-A22B-Instruct-2507-FP8',
            'temperature': 0.4,
        })
    if 'medical' in message_text.lower() or 'health' in message_text.lower() or 'patient' in message_text.lower():
        judges.append({
            'name': 'medical_expert',
            'prompt': palpersonalities.medical_expert,
            'openai_base_url': akash_base_url,
            'openai_model': 'DeepSeek-V3-1',
            'temperature': 0.4,
        })
    if 'environmental' in message_text.lower() or 'climate' in message_text.lower() or 'ecology' in message_text.lower():
        judges.append({
            'name': 'environmental_expert',
            'prompt': palpersonalities.environmental_expert,
            'openai_base_url': akash_base_url,
            'openai_model': 'gpt-oss-120b',
            'temperature': 0.4,
        })

    return judges

async def get_single_judgement(judge, message_text):
    try:
        use_akash = bool('akash' in judge['openai_base_url'])
        selected_client = akash_client if use_akash else openai_client

        judge_messages = [
            {'role': 'system', 'content': judge['prompt']},
            {'role': 'user', 'content': message_text},
        ]
        response = await selected_client.chat.completions.create(
            model=judge['openai_model'],
            messages=judge_messages,  # noqa
            max_tokens=512,
            temperature=judge['temperature'],
        )

        result = response.choices[0].message.content or ""
        print(f'{judge["name"]} judgement: {result}', flush=True)

        # Parse confidence
        confidence_match = re.search(r'Confidence: (\d+)/10', result)
        confidence = int(confidence_match.group(1)) if confidence_match else 5

        return {'content': result, 'confidence': confidence, 'name': judge['name']}

    except Exception as err:
        print(f'Error getting judgement from {judge["name"]}: {err}', flush=True)
        return {'content': f'Unable to obtain judgement from {judge["name"]}.', 'confidence': 1, 'name': judge['name']}

async def get_judge_responses(judges, message_text):
    tasks = []
    for judge in judges:
        task = asyncio.create_task(get_single_judgement(judge, message_text))
        tasks.append(task)

    return await asyncio.gather(*tasks)

def detect_consensus(judgements, threshold=0.8):
    if len(judgements) < 2:
        return False

    # Simple consensus: all judges agree on positive/negative outcome
    sentiments = []
    for judgement in judgements:
        content = judgement['content'].lower()
        if 'approve' in content or 'good' in content or 'acceptable' in content:
            sentiments.append(1)
        elif 'disapprove' in content or 'bad' in content or 'unacceptable' in content:
            sentiments.append(-1)
        else:
            sentiments.append(0)

    agreement_ratio = sentiments.count(sentiments[0]) / len(sentiments) if sentiments else 0
    return agreement_ratio >= threshold and sentiments[0] != 0

async def get_final_judgement(judgements, message_text):
    final_judge = {
        'prompt': palpersonalities.online,
        'openai_base_url': openai_base_url,
        'openai_model': 'sonar-pro',
        'temperature': 0.4,
    }

    # Combine judgements with confidence scores
    judgement_context = '# Purpose\nAnalyze the judgement statement and the provided judgements below. Formulate a final evidence-based judgement.\n'
    judgement_context += f'# Judgement Statement\n{message_text}\n'

    for judgement in judgements:
        judgement_context += f'# Judgement from {judgement["name"]} (Confidence: {judgement["confidence"]}/10)\n'
        judgement_context += judgement['content'] + '\n'

    try:
        print(f'\nFinal Judge Context:\n{judgement_context}\n', flush=True)
        use_akash = bool('akash' in final_judge['openai_base_url'])
        selected_client = akash_client if use_akash else openai_client

        final_messages = [
            {'role': 'system', 'content': final_judge['prompt']},
            {'role': 'user', 'content': judgement_context},
        ]
        judgement_response = await selected_client.chat.completions.create(
            model=final_judge['openai_model'],
            messages=final_messages,  # noqa
            max_tokens=512,
            temperature=final_judge['temperature'],
        )

        judgement_result = judgement_response.choices[0].message.content
        print(f'\nFinal judgement response:\n{judgement_result}\n', flush=True)
        return judgement_result

    except Exception as err:
        print(f'Error getting final judgement: {err}', flush=True)
        return 'Unable to formulate final judgement due to technical issues.'

async def provide_judgement(event):
    message_text = event.get('message', '')
    if not message_text:
        return 'No judgement statement provided.'

    # Check cache first
    cached_result = await check_judgement_cache(message_text)
    if cached_result:
        print('Returning cached judgement', flush=True)
        return cached_result

    try:
        # Select judges based on content
        judges = select_expert_judges(message_text)

        # Get judgements in parallel
        print(f'Starting judgement process with {len(judges)} judges...', flush=True)
        judgements = await get_judge_responses(judges, message_text)

        if not judgements:
            return "Unable to gather sufficient judgements."

        # Check for consensus
        if detect_consensus(judgements):
            print('Consensus detected, returning first judge opinion', flush=True)
            result = judgements[0]['content']
        else:
            # Get final judgement from online judge
            result = await get_final_judgement(judgements, message_text)

        # Cache the result
        key = get_cache_key(message_text)
        judgement_cache[key] = {'result': result, 'timestamp': time.time()}

        return result

    except Exception as err:
        print(f'Judgement system error: {err}', flush=True)
        # Fallback to single judge mode
        try:
            fallback_judge = {
                'name': 'fallback',
                'prompt': palpersonalities.neutral,
                'openai_base_url': akash_base_url,
                'openai_model': 'Meta-Llama-3-3-70B-Instruct',
                'temperature': 0.5,
            }
            fallback_result = await get_single_judgement(fallback_judge, message_text)
            return fallback_result['content']
        except:
            return "Judgement system temporarily unavailable."


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


async def handle_youtube(message, event):
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


async def handle_guidance(message, event):
    await message.add_reaction('👍')
    print('Awaiting guidance...\n', flush=True)
    judgement_response = await provide_judgement(event)
    await send_message(message, judgement_response)


async def handle_online(message, event):
    await message.add_reaction('👍')
    print('Searching the interwebs...\n', flush=True)
    event.update({'channel_model': 'sonar-pro'})
    if not '+history' in message.content:
        event.update({'channel_history': ''})

    response, citations = await handle_message(event)
    await send_message(message, response)
    if citations and '+citations' in message.content:
        await send_message(message, citations)


async def handle_pal(message, event):
    await message.add_reaction('👍')
    print('Handling message...\n', flush=True)
    if not '+history' in message.content:
        event.update({'channel_history': ''})

    response, citations = await handle_message(event)
    await send_message(message, response)
    if citations and '+citations' in message.content:
        await send_message(message, citations)

command_dispatcher = [
    {
        'condition': lambda msg: all([
            bool(msg.channel.name == 'music'),
            bool(msg.content.startswith('get ') or msg.content.startswith('!get')),
            bool(is_youtube_url(msg.content)),
        ]),
        'handler': handle_youtube,
    },
    {
        'condition': lambda msg: msg.content.startswith(('guidance:', '!guidance', 'judgement:', '!judgement')),
        'handler': handle_guidance,
    },
    {
        'condition': lambda msg: msg.content.startswith('online:') or msg.content.startswith('!online'),
        'handler': handle_online,
    },
    {
        'condition': lambda msg: msg.content.startswith('hey pal') or msg.channel.name.startswith('pal-'),
        'handler': handle_pal,
    },
]


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

    # Dispatch commands using the command dispatcher
    for command in command_dispatcher:
        if command['condition'](message):
            await command['handler'](message, event)
            break


if __name__ == '__main__':
    async def main():
        # Run the Discord client
        await discord_client.start(discord_token)

    # Use asyncio.run to create a new event loop
    asyncio.run(main())
