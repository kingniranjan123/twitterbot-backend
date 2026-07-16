import pg8000.native as pg

db = pg.Connection(user='postgres.srgkjdgxdzqxflleqkse', password='Facudi@Int$tring', host='aws-0-ap-southeast-2.pooler.supabase.com', port=5432, database='postgres')

twitter_id = 'kannigal'
username = 'kannigal'

query = f'''
    INSERT INTO users (twitter_id, username, profile_pic, followers, following, rate_limit, likes_limit, comments_limit, retweets_limit, follows_limit, extraction_method)
    VALUES ('{twitter_id}', '{username}', 'https://avatar.iran.liara.run/public/boy', 0, 0, 10, 10, 10, 10, 10, 1)
    RETURNING id
'''

try:
    res = db.run(query)
    print("Success:", res)
except Exception as e:
    print("Error:", e)
