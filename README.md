# PAL (Personal Assistant Liaison)
PAL started as a South Park reply bot ("You're not my buddy, pal!").

Now it's a framework I use for automation within chat apps like Discord, and Slack.

# Capabilities
This bot is under development and is provided as-is. The goal with this project is to leverage paid-for AI LLMs in Discord.

# Configuration
Create a `.env` file with the following variables. I personally use Perplexity and Akash. Akash is a free OpenAI-compatible Chat API.

```bash
LOG_LEVEL=debug
ENVIRONMENT=home
REGION=local
VERSION=1.0.0
# Perplexity
OPENAI_API_KEY=''
OPENAI_BASE_URL='https://api.perplexity.ai'
OPENAI_MODEL='llama-3.1-8b-instruct'
# Akash
AKASH_API_KEY=''
AKASH_BASE_URL='https://chatapi.akash.network/api/v1'
AKASH_MODEL='DeepSeek-R1'
# Discord
DISCORD_TOKEN=''
```

A Python dictionary is used to define channel settings. This allows you to set the model and system prompt per channel.
```python
# Optionally set openai model at runtime
openai_model = os.getenv('OPENAI_MODEL', 'llama-3.1-8b-instruct')

# Configure openai model and prompt per channel.
channel_settings = {
    'default': {
        'openai_model': openai_model,
        'system_prompt': 'default',
    },
    'general': {
        'openai_model': 'llama-3.1-70b-instruct',
        'system_prompt': 'default',
    },
}
```

Prompts are configured in their own dictionary. The key is referenced in the aforementioned `channel_settings` under `system_prompt`.
```python
# Configure dictionary for various prompts
system_prompt_dict = {
    'default': palpersonalities.default,
    'conservative': palpersonalities.conservative,
    'liberal': palpersonalities.liberal,
    'online': palpersonalities.online,
    'neutral': palpersonalities.neutral,
}
```

# Components
**local.sh** - Build and run PAL locally
**docker-compose.yml** - Build and run PAL as a service
**paldiscord.py** - "Main" Python module
**palpersonalities.py** - System prompt definitions
**requirements.txt** - Python requirements (Docker)
