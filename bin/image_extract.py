import MySQLdb.cursors
import pathlib
import os


static_path = pathlib.Path(__file__).resolve().parent.parent / 'private_isu/webapp/public'
_config = None


def config():
    global _config
    if _config is None:
        _config = {
            "db": {
                "host": os.environ.get("ISUCONP_DB_HOST", 'localhost'),
                "port": int(os.environ.get("ISUCONP_DB_PORT", "3306")),
                "user": os.environ.get("ISUCONP_DB_USER", "root"),
                "db": os.environ.get("ISUCONP_DB_NAME", "isuconp"),
            },
        }
        password = os.environ.get("ISUCONP_DB_PASSWORD")
        if password:
            _config['db']['passwd'] = password
    return _config


_db = None


def db():
    global _db
    if _db is None:
        conf = config()["db"].copy()
        conf['charset'] = 'utf8mb4'
        conf['cursorclass'] = MySQLdb.cursors.DictCursor
        conf['autocommit'] = True
        _db = MySQLdb.connect(**conf)
    return _db


def image_url(post):
    ext = ""
    mime = post['mime']
    if mime == "image/jpeg":
        ext = ".jpg"
    elif mime == "image/png":
        ext = ".png"
    elif mime == "image/gif":
        ext = ".gif"

    return "/image/%s%s" % (post['id'], ext)


cursor = db().cursor()
cursor.execute('SELECT MIN(`id`) AS min_id, MAX(`id`) AS max_id FROM `posts`')
count = cursor.fetchone()
min_id = count['min_id']
max_id = count['max_id'] + 1

for id in range(min_id, max_id):
    cursor.execute('SELECT `id`, `imgdata`, `mime` FROM `posts` WHERE `id` = %s', (id,))
    post = cursor.fetchone()
    file_name = image_url({"id": post['id'], "mime": post['mime']})
    file_path = str(static_path) + file_name
    print(file_path)
    if (os.path.exists(file_path)):
        os.remove(file_path)
    file = open(file_path, 'wb')
    file.write(post['imgdata'])
    file.close()
