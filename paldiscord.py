#!/usr/bin/python3
import asyncio
import os
import discord
import re
from openai import AsyncOpenAI
import palpersonalities

# Load environment variables
discord_token = os.getenv('DISCORD_TOKEN', 'not_set')
openai_api_key = os.getenv('OPENAI_API_KEY', 'not_set')
openai_base_url = os.getenv('OPENAI_BASE_URL', 'not_set')
openai_model = os.getenv('OPENAI_MODEL', 'not_set')

# Set up Discord client
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
discord_client = discord.Client(intents=intents)
print(f'DEBUG discord_client: {discord_client}', flush=True)

# Set up OpenAI client
openai_client = AsyncOpenAI(api_key=openai_api_key, base_url=openai_base_url)
print(f'DEBUG openai_client: {openai_client}', flush=True)

# Channel settings
channel_settings = {
    'default': {
        'openai_model': openai_model,
        'system_prompt': 'default',
    },
    'general': {
        'openai_model': 'llama-3.1-8b-instruct',
        'system_prompt': 'default',
    },
    'pal-online': {
        'openai_model': 'llama-3.1-sonar-small-128k-online',
        'system_prompt': 'online',
    },
    'pal-offline': {
        'openai_model': 'llama-3.1-8b-instruct',
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


async def generate_system_prompt_metadata(event):
    """
    Take the event dictionary we are passed and generate a system-prompt header for this event.
    """
    channel_name = event.get('channel_name')
    server_name = event.get('server_name')
    system_prompt = f'# Begin Context: Discord Metadata'
    system_prompt += f'\nChannel: {channel_name}\nServer: {server_name}'
    if bool(event.get('is_bot', False)):
        system_prompt += '\nYou are communicating with another bot.'
    else:
        user_name = event.get('user_name')
        system_prompt += f'\nYou are communicating with {user_name}'

    system_prompt += '\n# End Context: Discord Metadata'
    return system_prompt


async def handle_message(event):
    channel_model = event.get('channel_model', '')
    channel_prompt = event.get('channel_prompt', '')
    message_text = event.get('message', '')
    system_prompt_footer = event.get('channel_context', '')
    channel_history = event.get('channel_history', '')
    try:
        response = await openai_client.chat.completions.create(
            model=channel_model,
            messages=[
                {'role': 'system', 'content': channel_prompt + system_prompt_footer},
                {'role': 'user', 'content': message_text + channel_history},
            ],
            max_tokens=1024,
            temperature=0.7,
        )

        result = response.choices[0].message.content
        is_refusal = bool(response.choices[0].message.refusal)
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
        {'prompt': palpersonalities.conservative, 'temperature': 0.3},
        {'prompt': palpersonalities.liberal, 'temperature': 0.5},
    ]
    judgements = []
    if message_text:
        try:
            for judge in judges:
                print('Judging...', flush=True)
                response = await openai_client.chat.completions.create(
                    model=channel_settings['default']['openai_model'],
                    messages=[
                        {'role': 'system', 'content': judge['prompt']},
                        {'role': 'user', 'content': message_text},
                    ],
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
        judgement_context += f'# Judgement Statement\n{message_text}'
        for context in judgements:
            judgement_context += '# Judgement Provided\n'
            judgement_context += context + '\n'

        try:
            print(f'\nJudgement Context:\n{judgement_context}\n', flush=True)
            judgement_response = await openai_client.chat.completions.create(
                model=channel_model,
                messages=[
                    {'role': 'system', 'content': system_prompt_dict['neutral']},
                    {'role': 'user', 'content': judgement_context},
                ],
                max_tokens=512,
                temperature=0.1,
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
            chunk = msg_txt[i : i + 2000]
            try:
                await msg_obj.channel.send(chunk)
            except Exception as err:
                print(f'Error sending message: {err}')


@discord_client.event
async def on_ready():
    print(f'{discord_client.user} has connected to Discord!', flush=True)

    return


@discord_client.event
async def on_message(message):
    if message.author == discord_client.user:
        # Loop avoidance.
        print('Ignoring a message from myself.', flush=True)
        return

    try:
        await message.add_reaction('👍')
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

    if message.content.startswith('guidance:'):
        print('Awaiting guidance...\n', flush=True)
        judgement_response = await provide_judgement(event)
        await send_message(message, judgement_response)
        return

    if message.content.startswith('online:'):
        print('Searching the interwebs...\n', flush=True)
        event.update({'channel_model': 'llama-3.1-sonar-small-128k-online'})
        if not '+history' in message.content:
            event.update({'channel_history': ''})

        response, citations = await handle_message(event)
        await send_message(message, response)
        if citations and '+citations' in message.content:
            await send_message(message, citations)

        return

    if message.content.startswith('hey pal') or message.channel.name.startswith('pal-'):
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
