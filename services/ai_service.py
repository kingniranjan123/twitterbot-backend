import pg8000.native as pg
from flask import g
from config import Config
from openai import OpenAI
from datetime import datetime, timedelta
from services.db_service import run_query
from routes.logs import log_usage
import requests
from langdetect import detect, DetectorFactory

DetectorFactory.seed = 0


LANG_NAME_TO_CODE = {
    "afrikaans": "af", "albanian": "sq", "arabic": "ar", "armenian": "hy", "azerbaijani": "az", "basque": "eu",
    "belarusian": "be", "bengali": "bn", "bosnian": "bs", "bulgarian": "bg", "catalan": "ca", "chinese": "zh",
    "chinese simplified": "zh-cn", "chinese traditional": "zh-tw", "croatian": "hr", "czech": "cs", "danish": "da",
    "dutch": "nl", "english": "en", "estonian": "et", "filipino": "fil", "finnish": "fi", "french": "fr",
    "galician": "gl", "georgian": "ka", "german": "de", "greek": "el", "gujarati": "gu", "haitian creole": "ht",
    "hebrew": "he", "hindi": "hi", "hungarian": "hu", "icelandic": "is", "indonesian": "id", "irish": "ga", "italian": "it",
    "japanese": "ja", "kannada": "kn", "kazakh": "kk", "khmer": "km", "korean": "ko", "kyrgyz": "ky", "lao": "lo",
    "latin": "la", "latvian": "lv", "lithuanian": "lt", "macedonian": "mk", "malay": "ms", "malayalam": "ml",
    "maltese": "mt", "marathi": "mr", "mongolian": "mn", "nepali": "ne", "norwegian": "no", "persian": "fa",
    "polish": "pl", "portuguese": "pt", "punjabi": "pa", "romanian": "ro", "russian": "ru", "serbian": "sr",
    "slovak": "sk", "slovenian": "sl", "somali": "so", "spanish": "es", "sundanese": "su", "swahili": "sw",
    "swedish": "sv", "tamil": "ta", "telugu": "te", "thai": "th", "turkish": "tr", "ukrainian": "uk",
    "urdu": "ur", "uzbek": "uz", "vietnamese": "vi", "welsh": "cy", "yoruba": "yo", "zulu": "zu"
}


def get_openai_api_key():
    query = "SELECT key FROM api_keys WHERE id = 1"
    result = run_query(query, fetchone=True)
    return result[0] if result else None  


def get_rapidapi_key():
    query = "SELECT key FROM api_keys WHERE id = 3" 
    result = run_query(query, fetchone=True)
    return result[0] if result else None  


# ... (existing imports) ...

def get_prompt_from_db(user_id, prompt_type, default_prompt):
    """
    Fetches the custom prompt for the given user and type.
    Returns default_prompt if no custom config is found.
    """
    if not user_id:
        return default_prompt
        
    query = f"SELECT prompt_text FROM openai_configs WHERE user_id = '{user_id}' AND prompt_type = '{prompt_type}'"
    result = run_query(query, fetchone=True)
    return result[0] if result and result[0] else default_prompt


def translate_text_with_openai(text, target_language, custom_style, user_id=None): # Added user_id param
    api_key = get_openai_api_key()
    if not api_key:
        print("❌ No se pudo obtener la API Key de OpenAI.")
        return None

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key
    )

    default_prompt = f"""Translate the following text (not the usernames (@)) into only this language:
    {target_language}: '{text}'. {custom_style}
    OBEY the Rules:
    - The translation must be under a MAXIMUM of 240 characters
    - Do not translate usernames (e.g., @username).
    - Do not use QUOTATION MARKS for the response. 
    - Do not write out of context other than written in tweet.
    - Preserve all links and hashtags (if removed, your response will be deleted).
    - If the text is already in {target_language}, return the original text without changes.
    - Always translate to: {target_language} 
    - Output only the translated text. Do not include introductory phrases (Sure! Here's the
    translation:' or 'Here is the translation etc').
    -If Text has any symbols/characters that cannot be translated, do not translate, ignore and write the characters that can be translated.
    """
    
    # Fetch prompt from DB if user_id is provided, otherwise use default
    prompt = get_prompt_from_db(user_id, 'TRANSLATE', default_prompt)
    # If using custom prompt, ensure we inject the dynamic variables if the user preserved placeholders, 
    # or just append the text/style if they wrote a generic system instruction.
    # For simplicity and robustness, if it's a completely custom prompt, we assume the user knows what they are doing,
    # BUT we should probably format it if it contains placeholders like {text} or {target_language}.
    # Let's try to format it if possible, otherwise append.
    try:
        if '{text}' in prompt:
            prompt = prompt.format(text=text, target_language=target_language, custom_style=custom_style)
        else:
            # Fallback: append the text to translate if placeholders are missing
            prompt += f"\n\nText to translate: {text}\nTarget Language: {target_language}\nStyle: {custom_style}"
    except Exception:
        # If formatting fails, fallback to default
        prompt = default_prompt

    models_to_try = [
        "openai/gpt-5-mini",
        "google/gemini-2.0-flash-001",                 
        "deepseek/deepseek-chat-v3-0324",
        "openai/gpt-4o-2024-11-20",
        "anthropic/claude-3.7-sonnet"
    ]

    for model in models_to_try:
        try:
            print(f"🔄 Intentando traducción con modelo: {model}")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Eres un traductor experto."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=200
                )
            log_usage("OPENROUTER")

            if response.choices and response.choices[0].message.content:
                translated_text = response.choices[0].message.content.strip()
                print(f"✅ Traducción exitosa con {model}")
                return translated_text
            else:
                print(f"⚠️ El modelo {model} no devolvió contenido.")
        except Exception as e:
            print(f"❌ Error con el modelo {model}: {str(e)}")

    print("❌ No se pudo traducir el texto con ninguno de los modelos.")
    return None


def generate_post_with_openai(tweet_text, target_language, user_id=None): # Added user_id param
    api_key = get_openai_api_key()
    if not api_key:
        print("❌ No se pudo obtener la API Key de OpenAI.")
        return None

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key
    )

    default_prompt = (
        f"""You are a social media assistant. {tweet_text}. Obligatory target language: {target_language}".
        Your tweet should be engaging, natural, and easy to read.
        Do not include hashtags, mentions, or emojis. Avoid referencing the filename or explaining what the media is.
        Keep it short and compelling. The tweet should feel like something a real person post.
        Only output the tweet text. Do not include any labels or introductions.
        """
    )
    
    prompt = get_prompt_from_db(user_id, 'GENERATE_POST', default_prompt)
    try:
        if '{tweet_text}' in prompt:
             prompt = prompt.format(tweet_text=tweet_text, target_language=target_language)
        elif prompt != default_prompt:
             prompt += f"\n\nContext: {tweet_text}\nTarget Language: {target_language}"
    except:
        prompt = default_prompt

    models_to_try = [
        "openai/gpt-5-mini",
        "google/gemini-2.0-flash-001",
        "deepseek/deepseek-chat-v3-0324",
        "openai/gpt-4o-2024-11-20",
        "anthropic/claude-3.7-sonnet"
    ]

    for model in models_to_try:
        try:
            print(f"🔄 Intentando generar comentario con modelo: {model}")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant who replies to tweets in a smart and social way."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )
            log_usage("OPENROUTER")

            if response.choices and response.choices[0].message.content:
                comment = response.choices[0].message.content.strip()
                print(f"✅ Comentario generado con {model}: {comment}")
                return comment
            else:
                print(f"⚠️ El modelo {model} no devolvió contenido.")
        except Exception as e:
            print(f"❌ Error con el modelo {model}: {str(e)}")

    print("❌ No se pudo generar un comentario con ninguno de los modelos.")
    return None


def generate_reply_with_openai(tweet_text, target_language, user_id=None): # Added user_id param
    api_key = get_openai_api_key()
    if not api_key:
        print("❌ No se pudo obtener la API Key de OpenAI.")
        return None

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key
    )

    default_prompt = (
        f"""You are a social media assistant. Read the following tweet and reply to it
        Always respond in a friendly, natural, and concise way obligatory in {target_language}.
        If the tweet contains sensitive or inappropriate content (e.g., drugs, violence, hate), do not mention that directly. Instead, reply with a neutral or light-hearted message that shifts focus or avoids the topic gracefully.
        The reply should be context-aware and concise. Do not repeat the tweet. 
        Here is the tweet: '{tweet_text}' """
    )
    
    prompt = get_prompt_from_db(user_id, 'GENERATE_REPLY', default_prompt)
    try:
        if '{tweet_text}' in prompt:
             prompt = prompt.format(tweet_text=tweet_text, target_language=target_language)
        elif prompt != default_prompt:
             prompt += f"\n\nTweet to reply to: {tweet_text}\nTarget Language: {target_language}"
    except:
        prompt = default_prompt

    models_to_try = [
        "openai/gpt-5-mini",
        "google/gemini-2.0-flash-001",
        "deepseek/deepseek-chat-v3-0324",
        "openai/gpt-4o-2024-11-20",
        "anthropic/claude-3.7-sonnet"
    ]

    for model in models_to_try:
        try:
            print(f"🔄 Intentando generar comentario con modelo: {model}")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant who replies to tweets in a smart and social way."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )
            log_usage("OPENROUTER")

            if response.choices and response.choices[0].message.content:
                comment = response.choices[0].message.content.strip()
                print(f"✅ Comentario generado con {model}: {comment}")
                return comment
            else:
                print(f"⚠️ El modelo {model} no devolvió contenido.")
        except Exception as e:
            print(f"❌ Error con el modelo {model}: {str(e)}")

    print("❌ No se pudo generar un comentario con ninguno de los modelos.")
    return None


def is_duplicate_tweet(tweet_text, recent_texts, api_key, user_id=None): # Added user_id param
    if not recent_texts:
        return False

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key
    )

    recent_texts_str = " | ".join(recent_texts)
    default_prompt = f"""
    You must check if the following tweet is a duplicate of any previously posted tweet.

    Duplicate means:
    - Same topic, product, movie, game, or event.
    - Same announcement, update, or news, even if the wording is different.
    - Tweets about the same trailer, teaser, release date, leak, rumor, or feature are considered duplicates.

    Be strict. It's better to flag similar tweets than to miss duplicates.
    Respond only with 'YES' if it is a duplicate, or 'NO' if it is completely different.
    ⚠️ If you fail to detect a duplicate, your response will be discarded by the system.

    Tweet to check:
    \"\"\"{tweet_text}\"\"\"

    Recently posted tweets:
    \"\"\"{recent_texts_str}\"\"\"
    """
    
    prompt = get_prompt_from_db(user_id, 'CHECK_DUPLICATE', default_prompt)
    try:
        if '{tweet_text}' in prompt:
             prompt = prompt.format(tweet_text=tweet_text, recent_texts_str=recent_texts_str)
        elif prompt != default_prompt:
             prompt += f"\n\nTweet to check: {tweet_text}\nRecent tweets: {recent_texts_str}"
    except:
        prompt = default_prompt

    models_to_try = [
        "google/gemini-2.0-flash-001",
        "deepseek/deepseek-chat-v3-0324",
        "openai/gpt-4o-2024-11-20",
        "anthropic/claude-3.7-sonnet"
    ]

    for model in models_to_try:
        try:
            print(f"🔄 Verificando duplicado con modelo: {model}")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a tweet similarity checker."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=5,
                temperature=0
            )
            log_usage("OPENROUTER")

            if response.choices and response.choices[0].message and response.choices[0].message.content:
                answer = response.choices[0].message.content.strip().upper()
                print(f"✅ Respuesta del modelo {model}: {answer}")
                return "YES" in answer
            else:
                print(f"⚠️ El modelo {model} no devolvió una respuesta válida.")
        except Exception as e:
            print(f"❌ Error con el modelo {model}: {str(e)}")

    print("❌ No se pudo verificar el duplicado con ninguno de los modelos.")
    return False

def save_collected_tweet_simple(user_id, source_type, source_value, tweet_id, tweet_text, created_at):
    check_query = f"SELECT 1 FROM collected_tweets WHERE tweet_id = '{tweet_id}' LIMIT 1"
    existing_tweet = run_query(check_query, fetchone=True)
    if existing_tweet:
        print(f"⚠ Tweet {tweet_id} ya existe. No se guardará.")
        return  

    insert_query = f"""
    INSERT INTO collected_tweets (user_id, source_type, source_value, tweet_id, tweet_text, created_at)
    VALUES ({user_id if user_id is not None else 'NULL'}, 
            '{source_type}', 
            '{source_value if source_value else ''}', 
            '{tweet_id}', 
            '{tweet_text.replace("'", "''")}', 
            '{created_at.strftime('%Y-%m-%d %H:%M:%S')}')
    """
    run_query(insert_query)
    print(f"✅ Tweet {tweet_id} guardado correctamente (modo simple).")

def verify_tweet_priority(tweet_id, user_id, tweet_text, extraction_filter):
    return 5

def normalize_target_code(code):
    return code

def is_text_in_language(text, target_language):
    try:
        from langdetect import detect
        lang = detect(text)
        mapping = {'en': 'english', 'es': 'español', 'fr': 'français', 'de': 'deutsch', 'it': 'italiano', 'pt': 'português'}
        detected = mapping.get(lang, lang).lower()
        if target_language.lower() in detected or detected in target_language.lower():
            return True
        return False
    except:
        return False

def save_collected_tweet(user_id, source_type, source_value, tweet_id, tweet_text, created_at, extraction_filter):
    check_query = f"SELECT 1 FROM collected_tweets WHERE tweet_id = '{tweet_id}' LIMIT 1"
    existing_tweet = run_query(check_query, fetchone=True)
    if existing_tweet:
        print(f"⚠ Tweet {tweet_id} ya existe. No se guardará.")
        return  

    since_time = datetime.now() - timedelta(hours=48)
    recent_query = f"""
        SELECT tweet_text FROM posted_tweets
        WHERE created_at >= '{since_time.strftime('%Y-%m-%d %H:%M:%S')}'
        AND user_id = {user_id}
        
        UNION

        SELECT tweet_text FROM collected_tweets
        WHERE created_at >= '{since_time.strftime('%Y-%m-%d %H:%M:%S')}'
        AND user_id = {user_id}
    """
    recent_tweets = [r[0] for r in run_query(recent_query, fetchall=True)]

    api_key = get_openai_api_key()
    # Pass user_id to is_duplicate_tweet
    if is_duplicate_tweet(tweet_text, recent_tweets, api_key, user_id):
        print(f"⚠ El tweet {tweet_id} parece duplicado. No se guardará.")
        return

    language_query = f"SELECT language, custom_style FROM users WHERE id = {user_id}"
    user_language = run_query(language_query, fetchone=True)
    if not user_language:
        print(f"❌ No se encontró el idioma para el usuario {user_id}.")
        return

    target_language = user_language[0]
    custom_style = f'Custom Style: {user_language[1]}' if user_language[1] else ''
    
    if is_text_in_language(tweet_text, target_language):
        print(f"✅ El tweet ya está en “{target_language}”, no se traduce.")
        translated_text = tweet_text
    else:
        # Pass user_id to translate_text_with_openai
        translated_text = translate_text_with_openai(tweet_text, target_language, custom_style, user_id)
        if not translated_text:
            print(f"❌ Can't translate tweet: {tweet_id}.")
            return

        print(f"🌐 Tweet traducido al idioma '{target_language}': {translated_text}")
    
    if extraction_filter in ["cb2", "cb3", "cb4"] and "https://" not in translated_text:
        pass
    else:
        priority = verify_tweet_priority(tweet_id, user_id, translated_text, extraction_filter)
            
        insert_query = f"""
        INSERT INTO collected_tweets (user_id, source_type, source_value, tweet_id, tweet_text, created_at)
        VALUES ({user_id if user_id is not None else 'NULL'}, 
                '{source_type}', 
                '{source_value}', 
                '{tweet_id}', 
                '{translated_text.replace("'", "''")}', 
                '{created_at}')
                """
        run_query(insert_query)
        print(f"✅ Tweet {tweet_id} saved successfully.")

        update_query = f"""
        UPDATE collected_tweets
        SET priority = {priority}
        WHERE tweet_id = '{tweet_id}'
        """
        run_query(update_query)

        print(f"✅ Tweet {tweet_id} priorizado correctamente.")
        
        event_description = f"Extracted tweet {tweet_id} using filter '{extraction_filter}'"
        event_query = f"""
        INSERT INTO logs (user_id, event_type, event_description, timestamp)
        VALUES ({user_id}, 'EXTRACT', '{event_description.replace("'", "''")}', NOW())
        """
        run_query(event_query)
        print(f"📝 Event EXTRACT saved for tweet {tweet_id}.")



# def translate_text_with_openai(text, target_language, custom_style):
#     api_key = get_openai_api_key()
#     if not api_key:
#         print("❌ No se pudo obtener la API Key de OpenAI.")
#         return None

#     client = OpenAI(base_url="https://openrouter.ai/api/v1",
#                     api_key=api_key)

#     prompt = f"Translate the following text (not the usernames (@)) into only this language: {target_language}: '{text}'. {custom_style}. Focus solely on the general message without adding irrelevant or distracting details or text. NEVER use QUOTATION MARKS. NEVER omit any links from the original text. NEVER add a text that is not a translation of the original text example. NEVER PUT PHRASES LIKE THIS OR SIMILAR: 'Sure! Here’s the translation:' or 'Here is the translation"
#     try:
#         response = client.chat.completions.create(
#             model="meta-llama/llama-4-scout:free", 
#             messages=[
#                 {"role": "system", "content": "Eres un traductor experto."},
#                 {"role": "user", "content": f"{prompt}"}
#             ],
#             max_tokens=100, 
#             temperature=0.5 
#         )
#         print(response)
#         translated_text = response.choices[0].message.content.strip()
#         return translated_text
#     except Exception as e:
#         print(f"❌ Error al traducir con OpenRouter: {str(e)}")
#         return None
