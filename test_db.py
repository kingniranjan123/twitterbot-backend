import pg8000.native as pg
db = pg.Connection(user='postgres.srgkjdgxdzqxflleqkse', password='Facudi@Int$tring', host='aws-0-ap-southeast-2.pooler.supabase.com', port=5432, database='postgres')
res = db.run("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'users'")
print(res)
